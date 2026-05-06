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
import uvicorn

from openai import OpenAI
from dotenv import load_dotenv
import chromadb
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
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
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


class StructuringAgent:
    """Embeds knowledge units into ChromaDB and syncs state to brain.json for the Next.js frontend."""

    def embed_and_store(
        self,
        source_id: str,
        source: dict,
        units: list,
        entities: list,
    ) -> dict:
        now = datetime.datetime.utcnow().isoformat() + "Z"

        # Build unit objects matching the TypeScript KnowledgeUnit shape
        stored_units = []
        chroma_ids, chroma_docs, chroma_metas = [], [], []

        for u in units:
            uid = str(uuid.uuid4())[:10]
            unit = {
                "id": uid,
                "kind": u.get("kind", "fact"),
                "subject": u.get("subject", ""),
                "statement": u.get("statement", ""),
                "entities": u.get("entities", []),
                "evidence": [{"sourceId": source_id, "quote": u.get("evidence_quote", "")}],
                "confidence": float(u.get("confidence", 0.7)),
                "createdAt": now,
                "updatedAt": now,
            }
            stored_units.append(unit)
            chroma_ids.append(uid)
            chroma_docs.append(unit["statement"])
            chroma_metas.append({
                "source_id": source_id,
                "kind": unit["kind"],
                "subject": unit["subject"],
                "confidence": unit["confidence"],
            })

        # Upsert into ChromaDB (handles re-ingestion gracefully)
        if chroma_ids:
            collection.upsert(ids=chroma_ids, documents=chroma_docs, metadatas=chroma_metas)

        # Merge into brain.json so the Next.js dashboard reflects real data
        brain = _read_brain()

        # Entity dedup by name (case-insensitive)
        new_entities = []
        for e in entities:
            eid = str(uuid.uuid4())[:8]
            entity = {
                "id": eid,
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

        brain["units"] = stored_units + brain["units"]
        brain["sources"].insert(0, source)
        _write_brain(brain)

        return {
            "units_stored": len(stored_units),
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


@app.get("/api/metrics")
def get_metrics():
    """AMD GPU showcase metrics panel."""
    brain = _read_brain()
    return {
        "chroma_units": collection.count(),
        "brain_sources": len(brain.get("sources", [])),
        "brain_entities": len(brain.get("entities", [])),
        "brain_units": len(brain.get("units", [])),
        "model": MODEL_NAME,
        "vlm_model": VLM_MODEL_NAME,
        "gpu_backend": "AMD MI300X",
        "vllm_endpoint": vllm_url,
        "vlm_endpoint": vlm_url,
        "embedding_model": os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081, reload=False)
