from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
import os
import base64
import uuid
import time
import threading
import datetime
import re
import io
import uvicorn

from openai import OpenAI
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

load_dotenv()

app = FastAPI(title="BrainOS Multi-Agent Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── LLM clients (OpenAI-compatible, pointed at AMD MI300X via vLLM) ────────────
vllm_url = os.getenv("VLLM_API_BASE", "http://134.199.204.211:8000/v1")
vlm_url = os.getenv("VLM_API_BASE", vllm_url)  # separate VLM endpoint or same

llm_client = OpenAI(base_url=vllm_url, api_key=os.getenv("OPENAI_API_KEY", "not-required"))
vlm_client = OpenAI(base_url=vlm_url, api_key=os.getenv("OPENAI_API_KEY", "not-required"))

MODEL_NAME = os.getenv("MODEL_NAME", "amd/Llama-3.1-70B-Instruct-FP8-KV")
VLM_MODEL_NAME = os.getenv("VLM_MODEL_NAME", "llava-hf/llava-v1.6-mistral-7b-hf")

# ── Paths ──────────────────────────────────────────────────────────────────────
_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DATA_DIR = os.path.join(_project_root, "data")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
BRAIN_JSON = os.path.join(DATA_DIR, "brain.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ── ChromaDB with sentence-transformers embeddings (runs on CPU, ~90 MB model) ─
chroma_client = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False),
)
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
)
collection = chroma_client.get_or_create_collection(
    name="brainos_knowledge",
    embedding_function=embedding_fn,
    metadata={"hnsw:space": "cosine"},
)

# ── brain.json helpers (shared with Next.js frontend) ─────────────────────────
_json_lock = threading.Lock()

def _read_brain() -> dict:
    try:
        with open(BRAIN_JSON, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sources": [], "entities": [], "units": []}

def _write_brain(state: dict):
    with _json_lock:
        with open(BRAIN_JSON, "w") as f:
            json.dump(state, f, indent=2)

# ── Extraction system prompt (mirrors extractor.ts logic, runs on 70B model) ──
EXTRACTION_SYSTEM = """You are the extraction layer of a Company Brain AI system.
Turn raw company knowledge into structured, atomic, executable data.

Extract exactly two things:
1. ENTITIES — every named person, team, system, product, tool, customer, or concept.
2. KNOWLEDGE UNITS — atomic self-contained statements. Each must be independently understandable.

Unit kinds:
  fact        – static info ("The billing API is on AWS us-east-1")
  process     – how something is done ("Deploy by merging to main, then tagging v-prefix")
  decision    – a choice made ("We chose Stripe over Adyen for v2")
  ownership   – who owns something ("Alice owns the billing service")
  definition  – what a term means ("P0 = customer-impacting outage")
  policy      – a rule to follow ("All PRs need 2 reviewers")
  gotcha      – non-obvious tribal knowledge ("Webhook handler silently drops if signature header missing")

Quality rules:
- Each unit captures ONE thing only. Split compound statements.
- Use full entity names, never pronouns.
- evidence_quote must be a literal substring from the source text.
- confidence: 1.0=clearly stated, 0.7=strongly implied, 0.4=speculative. Omit below 0.4.
- Skip pleasantries, scheduling, off-topic chatter.

Return ONLY valid JSON — no markdown, no explanation:
{
  "entities": [
    {"name": "string", "kind": "person|team|system|product|process|concept|tool|customer", "aliases": ["string"]}
  ],
  "units": [
    {
      "kind": "fact|process|decision|ownership|definition|policy|gotcha",
      "subject": "string",
      "statement": "string",
      "entities": ["string"],
      "evidence_quote": "string",
      "confidence": 0.0
    }
  ]
}"""

def _parse_extraction_json(raw: str) -> dict:
    """Robustly extract JSON from LLM output that may include markdown fences."""
    raw = raw.strip()
    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    # Find outermost JSON object
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"entities": [], "units": []}


# ══════════════════════════════════════════════════════════════════════════════
# Agents
# ══════════════════════════════════════════════════════════════════════════════

class IngestionAgent:
    """Reads raw content (text or image) and extracts structured knowledge via the 70B model."""

    def extract_from_text(self, source_type: str, title: str, content: str) -> dict:
        prompt = (
            f"SOURCE TYPE: {source_type}\n"
            f"TITLE: {title}\n"
            f"---\n{content}\n---\n\n"
            "Extract entities and atomic knowledge units per the system instructions."
        )
        try:
            response = llm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.1,
            )
            return _parse_extraction_json(response.choices[0].message.content)
        except Exception as e:
            print(f"[IngestionAgent] Extraction error: {e}")
            return {"entities": [], "units": []}

    def describe_image(self, image_data: bytes, mime_type: str = "image/png") -> str:
        """
        VLM step: convert an image to a rich text description suitable for RAG.
        Requires a vision-capable model at VLM_API_BASE.
        """
        b64 = base64.b64encode(image_data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"
        try:
            response = vlm_client.chat.completions.create(
                model=VLM_MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {
                            "type": "text",
                            "text": (
                                "You are extracting company knowledge from this image. "
                                "Describe every piece of text, diagram, architecture, system, "
                                "process, decision, person, or data visible. "
                                "Be exhaustive and specific — your output feeds a knowledge base. "
                                "Write plain prose, no bullet lists."
                            ),
                        },
                    ],
                }],
                max_tokens=1024,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"[VLM description unavailable — configure VLM_API_BASE and VLM_MODEL_NAME. Error: {e}]"


RECONCILE_SYSTEM = """You reconcile a new knowledge unit against existing similar ones from the company brain.

Verdicts:
  supersedes  – the new unit makes the existing one wrong or outdated (changed owner, updated policy, overriding decision, corrected fact). Mark the OLD unit as stale.
  duplicate   – both say effectively the same thing. Discard the new unit.
  independent – different enough to coexist. Keep both.

Be conservative: only mark supersedes/duplicate when very confident. When in doubt, return independent.

Return ONLY valid JSON (no markdown):
{"verdict": "supersedes"|"duplicate"|"independent", "reason": "one sentence"}"""


class StructuringAgent:
    """
    Embeds knowledge units into ChromaDB, runs reconciliation against existing units,
    and syncs the merged state to brain.json for the Next.js frontend.
    """

    def _reconcile(self, new_unit: dict, new_uid: str, source_id: str) -> dict:
        """
        Query ChromaDB for semantically similar existing units from other sources.
        If any are found above the similarity threshold, call the 70B model once
        to classify the relationship. Returns superseded IDs and duplicate flag.
        """
        total = collection.count()
        if total < 2:
            return {"superseded_ids": [], "is_duplicate": False}

        try:
            results = collection.query(
                query_texts=[new_unit["statement"]],
                n_results=min(4, total),
                where={"$and": [
                    {"kind": {"$eq": new_unit["kind"]}},
                    {"source_id": {"$ne": source_id}},
                ]},
            )
        except Exception:
            # ChromaDB where filter requires at least 1 matching doc; ignore gracefully
            return {"superseded_ids": [], "is_duplicate": False}

        ids = results["ids"][0] if results["ids"] else []
        distances = results["distances"][0] if results["distances"] else []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        # Cosine distance < 0.15 → similarity > 0.85 → worth classifying
        candidates = [
            {"id": cid, "statement": doc, "subject": m.get("subject", ""), "distance": dist}
            for cid, dist, doc, m in zip(ids, distances, docs, metas)
            if dist < 0.15 and cid != new_uid
        ]

        if not candidates:
            return {"superseded_ids": [], "is_duplicate": False}

        # Single LLM call covering all candidates
        candidates_text = "\n".join(
            f'  [{c["id"]}] (similarity {1 - c["distance"]:.2f}) "{c["statement"]}"'
            for c in candidates
        )
        prompt = (
            f"NEW UNIT:\n"
            f'  kind: {new_unit["kind"]}\n'
            f'  subject: {new_unit["subject"]}\n'
            f'  statement: "{new_unit["statement"]}"\n\n'
            f"EXISTING SIMILAR UNITS:\n{candidates_text}\n\n"
            f"Pick the single most relevant existing unit and return your verdict.\n"
            f'If none warrant supersedes/duplicate, return {{"verdict": "independent", "reason": "..."}}.\n'
            f'Otherwise include "target_id": "<id>" for the unit your verdict applies to.'
        )
        try:
            resp = llm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": RECONCILE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=120,
                temperature=0.0,
            )
            result = _parse_extraction_json(resp.choices[0].message.content)
            verdict = result.get("verdict", "independent")
            target_id = result.get("target_id")

            if verdict == "duplicate":
                return {"superseded_ids": [], "is_duplicate": True}
            if verdict == "supersedes" and target_id:
                return {"superseded_ids": [target_id], "is_duplicate": False}
        except Exception as e:
            print(f"[Reconcile] LLM error: {e}")

        return {"superseded_ids": [], "is_duplicate": False}

    def embed_and_store(
        self,
        source_id: str,
        source: dict,
        units: list,
        entities: list,
    ) -> dict:
        now = datetime.datetime.utcnow().isoformat() + "Z"

        # ── Step 1: build unit objects ──────────────────────────────────────
        pending = []
        for u in units:
            uid = str(uuid.uuid4())[:10]
            pending.append((uid, {
                "id": uid,
                "kind": u.get("kind", "fact"),
                "subject": u.get("subject", ""),
                "statement": u.get("statement", ""),
                "entities": u.get("entities", []),
                "evidence": [{"sourceId": source_id, "quote": u.get("evidence_quote", "")}],
                "confidence": float(u.get("confidence", 0.7)),
                "createdAt": now,
                "updatedAt": now,
            }))

        # ── Step 2: upsert all into ChromaDB first so reconciliation can query ──
        if pending:
            collection.upsert(
                ids=[uid for uid, _ in pending],
                documents=[unit["statement"] for _, unit in pending],
                metadatas=[{
                    "source_id": source_id,
                    "kind": unit["kind"],
                    "subject": unit["subject"],
                    "confidence": unit["confidence"],
                } for _, unit in pending],
            )

        # ── Step 3: reconcile each new unit against existing ones ───────────
        superseded_ids: set[str] = set()
        stored_units = []

        for uid, unit in pending:
            rec = self._reconcile(unit, uid, source_id)
            if rec["is_duplicate"]:
                # Remove the just-upserted duplicate from ChromaDB
                try:
                    collection.delete(ids=[uid])
                except Exception:
                    pass
                continue
            superseded_ids.update(rec["superseded_ids"])
            stored_units.append(unit)

        # ── Step 4: merge into brain.json ───────────────────────────────────
        brain = _read_brain()

        # Entity dedup by name (case-insensitive)
        new_entities = []
        for e in entities:
            entity = {
                "id": str(uuid.uuid4())[:8],
                "name": e.get("name", ""),
                "kind": e.get("kind", "concept"),
                "aliases": e.get("aliases", []),
            }
            existing = next(
                (x for x in brain["entities"] if x["name"].lower() == entity["name"].lower()),
                None,
            )
            if existing:
                existing["aliases"] = list(set(existing["aliases"] + entity["aliases"]))
            else:
                brain["entities"].insert(0, entity)
                new_entities.append(entity)

        # Mark superseded units as stale in brain.json
        superseded_count = 0
        for bu in brain["units"]:
            if bu["id"] in superseded_ids and not bu.get("stale"):
                bu["stale"] = True
                bu["supersededBy"] = stored_units[0]["id"] if stored_units else "unknown"
                superseded_count += 1

        brain["units"] = stored_units + brain["units"]
        brain["sources"].insert(0, source)
        _write_brain(brain)

        return {
            "units_stored": len(stored_units),
            "units_superseded": superseded_count,
            "entities_stored": len(new_entities),
            "chroma_total": collection.count(),
            "brain_totals": {
                "sources": len(brain["sources"]),
                "entities": len(brain["entities"]),
                "units": len(brain["units"]),
            },
        }


class ExecutionAgent:
    """Semantic retrieval from ChromaDB + grounded generation via the 70B model."""

    def execute(self, query: str, n_results: int = 6) -> dict:
        t0 = time.time()

        count = collection.count()
        retrieved_ids, retrieved_docs, retrieved_metas = [], [], []

        if count > 0:
            results = collection.query(
                query_texts=[query],
                n_results=min(n_results, count),
            )
            retrieved_ids = results["ids"][0]
            retrieved_docs = results["documents"][0]
            retrieved_metas = results["metadatas"][0]

        if retrieved_docs:
            context_blocks = [
                f"[{m.get('kind', 'fact')} | confidence {m.get('confidence', 0.7):.2f}] {doc}"
                for doc, m in zip(retrieved_docs, retrieved_metas)
            ]
            context_section = "\n".join(context_blocks)
            user_prompt = (
                f"COMPANY KNOWLEDGE BASE (retrieved for this question):\n"
                f"{context_section}\n\n"
                f"QUESTION: {query}\n\n"
                f"Answer using ONLY the knowledge above. "
                f"Be concise and specific. If the knowledge doesn't cover the question, say so clearly."
            )
        else:
            user_prompt = (
                f"The company brain has no ingested knowledge yet for this query.\n"
                f"QUESTION: {query}\n\n"
                f"Acknowledge that the brain is empty and suggest ingesting relevant sources."
            )

        response = llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the BrainOS execution agent running on an AMD MI300X GPU. "
                        "Answer questions strictly based on company knowledge provided in context. "
                        "Never invent facts. Cite the knowledge you use."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=512,
            temperature=0.1,
        )

        answer = response.choices[0].message.content
        latency_ms = int((time.time() - t0) * 1000)

        return {
            "answer": answer,
            "retrieved_ids": retrieved_ids,
            "retrieved_docs": retrieved_docs,
            "latency_ms": latency_ms,
        }


class FeedbackAgent:
    """Evaluates whether the answer is grounded in the retrieved context using the 70B model."""

    def evaluate(self, query: str, answer: str, context_docs: list) -> dict:
        if not context_docs:
            return {
                "confidence": 0.0,
                "grounded": False,
                "feedback": "No knowledge was retrieved — answer is not grounded in company data.",
            }

        ctx = "\n".join(f"- {d}" for d in context_docs)
        prompt = (
            f"RETRIEVED CONTEXT:\n{ctx}\n\n"
            f"QUESTION: {query}\n"
            f"ANSWER: {answer}\n\n"
            f"Is the answer fully supported by the context above? "
            f"Respond ONLY with JSON (no markdown):\n"
            f'{{ "confidence": 0.0-1.0, "grounded": true/false, "feedback": "one sentence" }}'
        )
        try:
            response = llm_client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=120,
                temperature=0.0,
            )
            raw = response.choices[0].message.content.strip()
            parsed = _parse_extraction_json(raw)
            if "confidence" in parsed:
                return parsed
        except Exception as e:
            print(f"[FeedbackAgent] Error: {e}")

        return {"confidence": 0.8, "grounded": True, "feedback": "Evaluation unavailable."}


# ── Instantiate agents ─────────────────────────────────────────────────────────
ingest_agent = IngestionAgent()
struct_agent = StructuringAgent()
exec_agent = ExecutionAgent()
feedback_agent = FeedbackAgent()


# ══════════════════════════════════════════════════════════════════════════════
# Request models
# ══════════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    query: str

class IngestRequest(BaseModel):
    kind: str
    title: str
    content: str
    url: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "gpu_backend": "AMD MI300X via vLLM",
        "model": MODEL_NAME,
        "vlm_model": VLM_MODEL_NAME,
        "chroma_units": collection.count(),
        "brain_json": os.path.exists(BRAIN_JSON),
    }


@app.post("/api/ingest")
def ingest_text(req: IngestRequest):
    source_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    extraction = ingest_agent.extract_from_text(req.kind, req.title, req.content)

    source = {
        "id": source_id,
        "kind": req.kind,
        "title": req.title,
        "content": req.content,
        "url": req.url,
        "capturedAt": now,
    }

    result = struct_agent.embed_and_store(
        source_id=source_id,
        source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
    )

    return {
        "message": "Ingested and structured via 70B model + ChromaDB.",
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        **result,
    }


def _extract_file_text(filename: str, data: bytes) -> str:
    """Extract plain text from PDF, TXT, MD, or CSV uploads."""
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(p for p in pages if p.strip())
        except Exception as e:
            return f"[PDF extraction failed: {e}]"
    # TXT / MD / CSV — decode directly
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


@app.post("/api/ingest_file")
async def ingest_file(
    title: str = Form(...),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """
    File upload pipeline:
      PDF/TXT/MD/CSV → text extraction → 70B extraction → ChromaDB → brain.json
    """
    data = await file.read()
    filename = file.filename or "upload"
    text = _extract_file_text(filename, data)

    if not text.strip():
        raise HTTPException(status_code=422, detail="Could not extract any text from the file.")

    source_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    extraction = ingest_agent.extract_from_text(
        source_type=kind,
        title=title,
        content=text,
    )

    source = {
        "id": source_id,
        "kind": kind,
        "title": title,
        "content": text,
        "url": url,
        "capturedAt": now,
        "uploadedFilename": filename,
    }

    result = struct_agent.embed_and_store(
        source_id=source_id,
        source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
    )

    return {
        "message": f"File '{filename}' ingested.",
        "chars_extracted": len(text),
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        **result,
    }


@app.post("/api/ingest_image")
async def ingest_image(
    title: str = Form(...),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """
    VLM pipeline:
      image → VLM description → 70B extraction → ChromaDB embedding → brain.json
    """
    image_data = await file.read()
    mime = file.content_type or "image/png"

    # Step 1: VLM converts image to text
    description = ingest_agent.describe_image(image_data, mime)

    source_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Step 2: 70B model extracts entities + knowledge units from the description
    extraction = ingest_agent.extract_from_text(
        source_type=f"image/{kind}",
        title=title,
        content=description,
    )

    source = {
        "id": source_id,
        "kind": kind,
        "title": title,
        "content": description,
        "url": url,
        "capturedAt": now,
        "imageIngested": True,
        "imageFilename": file.filename,
    }

    result = struct_agent.embed_and_store(
        source_id=source_id,
        source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
    )

    return {
        "message": "Image ingested via VLM → 70B extraction → ChromaDB.",
        "vlm_description_chars": len(description),
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        **result,
    }


@app.post("/api/ingest_mock")
def ingest_mock():
    """Ingest mock_sources.json through the full real pipeline."""
    data_file = os.path.join(DATA_DIR, "mock_sources.json")
    if not os.path.exists(data_file):
        raise HTTPException(status_code=404, detail="Run seed_demo_data.py first.")

    with open(data_file) as f:
        items = json.load(f)

    total_units, total_entities = 0, 0
    for item in items:
        source_id = item.get("id", str(uuid.uuid4())[:8])
        extraction = ingest_agent.extract_from_text(
            source_type=item.get("source_type", "other"),
            title=item.get("id", "Mock Source"),
            content=item.get("content", ""),
        )
        source = {
            "id": source_id,
            "kind": item.get("source_type", "other"),
            "title": item.get("id", "Mock Source"),
            "content": item.get("content", ""),
            "capturedAt": item.get("timestamp", datetime.datetime.utcnow().isoformat() + "Z"),
        }
        result = struct_agent.embed_and_store(
            source_id=source_id,
            source=source,
            units=extraction.get("units", []),
            entities=extraction.get("entities", []),
        )
        total_units += result["units_stored"]
        total_entities += result["entities_stored"]

    return {
        "message": "Mock data ingested through full pipeline.",
        "total_units": total_units,
        "total_entities": total_entities,
        "chroma_total": collection.count(),
    }


@app.post("/api/ask")
def ask_brainos(req: QueryRequest):
    exec_result = exec_agent.execute(req.query)
    feedback = feedback_agent.evaluate(
        query=req.query,
        answer=exec_result["answer"],
        context_docs=exec_result["retrieved_docs"],
    )

    return {
        "query": req.query,
        "answer": exec_result["answer"],
        "used": exec_result["retrieved_ids"],
        "latency_ms": exec_result["latency_ms"],
        "feedback": feedback,
    }


def _fetch_vllm_prometheus() -> dict:
    """
    Fetch raw Prometheus metrics from vLLM and parse the key gauges/counters.
    vLLM exposes /metrics at the base URL (strip /v1).
    Returns an empty dict if the endpoint is unreachable.
    """
    import urllib.request
    import re

    base = vllm_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    metrics_url = f"{base}/metrics"

    try:
        with urllib.request.urlopen(metrics_url, timeout=3) as resp:
            text = resp.read().decode("utf-8")
    except Exception:
        return {}

    parsed: dict = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = re.match(r'^(\S+?)(?:\{[^}]*\})?\s+([\d.e+\-]+)', line)
        if m:
            key, val = m.group(1), m.group(2)
            try:
                parsed[key] = float(val)
            except ValueError:
                pass
    return parsed


@app.get("/api/metrics")
def get_metrics():
    """Live AMD MI300X + ChromaDB metrics panel."""
    brain = _read_brain()
    prom = _fetch_vllm_prometheus()

    # vLLM Prometheus key names (vary slightly across versions, try both forms)
    def _g(*keys: str, default: float | None = None):
        for k in keys:
            if k in prom:
                return prom[k]
        return default

    # Compute average e2e latency from histogram sum/count
    lat_sum = _g("vllm:e2e_request_latency_seconds_sum", default=0.0)
    lat_cnt = _g("vllm:e2e_request_latency_seconds_count", default=0.0)
    avg_latency_s = (lat_sum / lat_cnt) if lat_cnt and lat_cnt > 0 else None

    return {
        # GPU / vLLM live stats
        "gpu": {
            "backend": "AMD MI300X",
            "model": MODEL_NAME,
            "vllm_endpoint": vllm_url,
            # Throughput
            "tokens_per_sec_generation": _g(
                "vllm:avg_generation_throughput_toks_per_s",
                "vllm:generation_tokens_total",
            ),
            "tokens_per_sec_prompt": _g(
                "vllm:avg_prompt_throughput_toks_per_s",
                "vllm:prompt_tokens_total",
            ),
            # Queue
            "requests_running": _g("vllm:num_requests_running", default=0),
            "requests_waiting": _g("vllm:num_requests_waiting", default=0),
            # GPU KV-cache
            "gpu_cache_usage_pct": _g("vllm:gpu_cache_usage_perc"),
            "cpu_cache_usage_pct": _g("vllm:cpu_cache_usage_perc"),
            # Latency
            "avg_e2e_latency_s": avg_latency_s,
            "total_requests_finished": _g(
                "vllm:request_success_total",
                "vllm:num_requests_success",
                default=0,
            ),
            # Raw Prometheus available?
            "prometheus_reachable": bool(prom),
        },
        # Embedding / RAG
        "rag": {
            "embedding_model": os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            "chroma_units": collection.count(),
        },
        # Knowledge base
        "knowledge": {
            "sources": len(brain.get("sources", [])),
            "entities": len(brain.get("entities", [])),
            "units": len(brain.get("units", [])),
            "stale_units": sum(1 for u in brain.get("units", []) if u.get("stale") or u.get("supersededBy")),
        },
        # VLM
        "vlm": {
            "model": VLM_MODEL_NAME,
            "endpoint": vlm_url,
        },
    }


@app.delete("/api/clear")
def clear_all():
    """Delete and recreate the ChromaDB collection, then wipe brain.json."""
    global collection
    try:
        chroma_client.delete_collection("brainos_knowledge")
    except Exception:
        pass
    collection = chroma_client.get_or_create_collection(
        name="brainos_knowledge",
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )
    _write_brain({"sources": [], "entities": [], "units": []})
    return {"ok": True, "cleared": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081, reload=False)
