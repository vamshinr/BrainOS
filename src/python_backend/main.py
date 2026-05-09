import json
import os
os.environ.setdefault("TQDM_DISABLE", "1")  # suppress sentence-transformers progress bar
import base64
import uuid
import time
import threading
import datetime
import re
import io
import collections
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from rank_bm25 import BM25Okapi
from pypdf import PdfReader
from openai import OpenAI
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from chromadb.api.types import Documents, Embeddings

os.environ["ANONYMIZED_TELEMETRY"] = "False"

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
vlm_url = os.getenv("VLM_API_BASE", vllm_url)

llm_client = OpenAI(base_url=vllm_url, api_key=os.getenv("OPENAI_API_KEY", "not-required"))
vlm_client = OpenAI(base_url=vlm_url, api_key=os.getenv("OPENAI_API_KEY", "not-required"))


def _resolve_model(client: OpenAI, env_name: str, env_value: str) -> str:
    """
    Verify the configured model name exists on the vLLM endpoint.
    If not, auto-select the first available model and warn.
    This prevents silent 0-unit extractions from a wrong model name.
    """
    try:
        available = [m.id for m in client.models.list().data]
    except Exception as e:
        print(f"[BrainOS] WARNING: could not list models from {client.base_url}: {e}")
        return env_value

    if not available:
        print(f"[BrainOS] WARNING: vLLM returned no models at {client.base_url}")
        return env_value

    if env_value in available:
        print(f"[BrainOS] {env_name}={env_value} ✓")
        return env_value

    # Configured name not found — auto-use the first served model
    auto = available[0]
    print(
        f"[BrainOS] WARNING: {env_name}='{env_value}' not found on vLLM.\n"
        f"  Available: {available}\n"
        f"  Auto-selecting: '{auto}'\n"
        f"  Fix: set {env_name}={auto} in .env"
    )
    return auto


# _model_env = os.getenv("MODEL_NAME", "amd/Llama-3.1-70B-Instruct-FP8-KV")
# _vlm_model_env = os.getenv("VLM_MODEL_NAME", "llava-hf/llava-v1.6-mistral-7b-hf")

_model_env = os.getenv("MODEL_NAME", "llava-hf/llava-v1.6-mistral-7b-hf")
_vlm_model_env = os.getenv("VLM_MODEL_NAME", "llava-hf/llava-v1.6-mistral-7b-hf")

MODEL_NAME = _resolve_model(llm_client, "MODEL_NAME", _model_env)
VLM_MODEL_NAME = _resolve_model(vlm_client, "VLM_MODEL_NAME", _vlm_model_env)


# ── Per-task model routing ────────────────────────────────────────────────────
# Lets you split work across two (or more) backends/models. Defaults to the
# global MODEL_NAME on VLLM_API_BASE for every task. Override individually:
#
#   EXTRACTION_MODEL=meta-llama/Llama-3.1-70B-Instruct
#   EXTRACTION_API_BASE=http://gpu1:8000/v1
#   RECONCILE_MODEL=Qwen/Qwen2.5-7B-Instruct
#   RECONCILE_API_BASE=http://gpu2:8000/v1
#   EXECUTE_MODEL=meta-llama/Llama-3.1-70B-Instruct  (defaults to MODEL_NAME)
#   FEEDBACK_MODEL=Qwen/Qwen2.5-7B-Instruct          (defaults to MODEL_NAME)
#   VLM_MODEL=...                                    (existing VLM_API_BASE/MODEL_NAME)
#
# Typical setup: heavy tasks (extraction, answer generation) on a 70B; light
# audit tasks (reconcile, feedback) on a 7B running cheaper.
TASKS = ["extraction", "reconcile", "execute", "feedback", "vlm"]


class ModelRouter:
    """Resolve (client, model) per task with per-task env overrides."""

    def __init__(self):
        self._client_cache: dict[str, OpenAI] = {
            vllm_url: llm_client,
            vlm_url: vlm_client,
        }
        self._routes: dict[str, tuple[OpenAI, str]] = {}
        for task in TASKS:
            self._routes[task] = self._resolve(task)

    def _resolve(self, task: str) -> tuple[OpenAI, str]:
        tu = task.upper()
        # VLM has historic env var names
        if task == "vlm":
            return vlm_client, VLM_MODEL_NAME
        api_base = os.getenv(f"{tu}_API_BASE", "").strip() or vllm_url
        model = os.getenv(f"{tu}_MODEL", "").strip() or MODEL_NAME
        if api_base not in self._client_cache:
            self._client_cache[api_base] = OpenAI(
                base_url=api_base,
                api_key=os.getenv("OPENAI_API_KEY", "not-required"),
            )
        return self._client_cache[api_base], model

    def get(self, task: str) -> tuple[OpenAI, str]:
        return self._routes.get(task, (llm_client, MODEL_NAME))

    def describe(self) -> list[dict]:
        out = []
        for task in TASKS:
            client, model = self._routes[task]
            base = str(client.base_url)
            shared_with_default = base.rstrip("/") == vllm_url.rstrip("/")
            out.append({
                "task": task,
                "model": model,
                "endpoint": base,
                "shared_with_default": shared_with_default,
            })
        return out


router = ModelRouter()
print("[BrainOS] Model routes:")
for r in router.describe():
    marker = "(default)" if r["shared_with_default"] else "(custom)"
    print(f"  {r['task']:12s} → {r['model']} {marker}")


# ── Model index — every model the user can select per-request ────────────────
# Aggregates models served by every endpoint we know about (the default text
# endpoint, the VLM endpoint, and any custom-route endpoints). Maps model id
# → which OpenAI client serves it. Used by the per-request override path so
# the dropdown on /ingest and /ask can show every reachable model.
def _build_model_index() -> dict[str, OpenAI]:
    index: dict[str, OpenAI] = {}
    seen_endpoints: set[str] = set()

    def _add(client: OpenAI):
        base = str(client.base_url).rstrip("/")
        if base in seen_endpoints:
            return
        seen_endpoints.add(base)
        try:
            for m in client.models.list().data:
                if m.id not in index:
                    index[m.id] = client
        except Exception as e:
            print(f"[BrainOS] Could not list models from {base}: {e}")

    _add(llm_client)
    _add(vlm_client)
    for task in TASKS:
        c, _ = router.get(task)
        _add(c)
    return index


_MODEL_INDEX: dict[str, OpenAI] = _build_model_index()
print(f"[BrainOS] Available models for per-request override: {sorted(_MODEL_INDEX.keys())}")


def _resolve_override(task: str, model_override: str | None) -> tuple[OpenAI, str]:
    """
    Returns (client, model). If `model_override` is set and known, use it (with
    its serving endpoint). Otherwise fall back to the routed default for the task.
    """
    if model_override:
        client = _MODEL_INDEX.get(model_override)
        if client is not None:
            return client, model_override
        print(f"[BrainOS] WARNING: requested model '{model_override}' not in index; "
              f"falling back to {task} default.")
    return router.get(task)


# ── Recent-calls log (in-memory ring buffer, surfaced to the dashboard) ──────
_call_log: collections.deque = collections.deque(maxlen=80)
_call_lock = threading.Lock()


def _log_call(
    task: str,
    model: str,
    latency_ms: int,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    ok: bool = True,
    note: str = "",
):
    with _call_lock:
        _call_log.append({
            "ts": datetime.datetime.utcnow().isoformat() + "Z",
            "task": task,
            "model": model,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "ok": ok,
            "note": note,
        })

# ── Paths ──────────────────────────────────────────────────────────────────────
_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DATA_DIR = os.path.join(_project_root, "data")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
BRAIN_JSON = os.path.join(DATA_DIR, "brain.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ── Embedding backend selection ────────────────────────────────────────────────
# If EMBEDDING_API_BASE is set → embeddings run on the AMD MI300X GPU via vLLM.
# Otherwise → sentence-transformers runs locally on CPU (~90 MB model).
#
# To enable GPU embeddings:
#   vllm serve BAAI/bge-large-en-v1.5 --task embed --port 8002
#   Then set EMBEDDING_API_BASE=http://<host>:8002/v1 in .env
#
# WARNING: switching backends changes vector dimensions. Run /api/clear first
# to rebuild the collection with the new embedding model.

_embed_api_base = os.getenv("EMBEDDING_API_BASE")
_embed_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


class VLLMEmbeddingFunction:
    """
    Calls vLLM's OpenAI-compatible /v1/embeddings endpoint on the AMD MI300X GPU.
    Requires a dedicated embedding model served via vLLM (e.g. BAAI/bge-large-en-v1.5).
    """
    def __init__(self, base_url: str, model: str, api_key: str = "not-required"):
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        texts = [t if isinstance(t, str) else t.decode("utf-8", errors="replace") for t in input]
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [e.embedding for e in response.data]


if _embed_api_base:
    embedding_fn = VLLMEmbeddingFunction(
        base_url=_embed_api_base,
        model=_embed_model,
        api_key=os.getenv("OPENAI_API_KEY", "not-required"),
    )
    EMBEDDING_BACKEND = f"GPU · vLLM · {_embed_model}"
else:
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=_embed_model
    )
    EMBEDDING_BACKEND = f"CPU · sentence-transformers · {_embed_model}"

print(f"[BrainOS] Embedding backend: {EMBEDDING_BACKEND}")

chroma_client = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False),
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

# ── In-memory BM25 + entity indexes ───────────────────────────────────────────
_bm25_index: object = None           # BM25Okapi instance (None until first ingest)
_bm25_unit_ids: list[str] = []       # parallel to _bm25_corpus
_bm25_corpus: list[str] = []         # raw unit statements
_entity_index: dict[str, set[str]] = {}  # entity_name_lower → {unit_id, ...}

def _build_indexes(brain: dict):
    """Rebuild BM25 + entity indexes from brain state. Called on startup and after every ingest."""
    global _bm25_index, _bm25_unit_ids, _bm25_corpus, _entity_index
    active = [u for u in brain.get("units", []) if not u.get("stale") and not u.get("supersededBy")]
    _bm25_unit_ids = [u["id"] for u in active]
    _bm25_corpus   = [u["statement"] for u in active]
    tokenized      = [stmt.lower().split() for stmt in _bm25_corpus]
    _bm25_index    = BM25Okapi(tokenized) if tokenized else None
    _entity_index  = {}
    for u in active:
        for ent in u.get("entities", []):
            key = ent.lower().strip()
            if key:
                _entity_index.setdefault(key, set()).add(u["id"])

def _rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion — combines ranked lists of unit IDs without weight tuning."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, uid in enumerate(ranked):
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: scores[x], reverse=True)

# Bootstrap indexes from persisted brain.json on startup
_startup_brain = _read_brain()
_build_indexes(_startup_brain)
del _startup_brain

# ── Extraction system prompt ───────────────────────────────────────────────────
EXTRACTION_SYSTEM = """You are the extraction layer of a Company Brain — a system that
turns scattered company knowledge into structured, atomic, executable data that AI agents
can load and act on.

Extract exactly THREE things:
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
- sector: classify the business function. Engineering=technical/infra/APIs/deployments, Finance=money/payments/billing/pricing, HR=people/hiring/policies/benefits, Legal=compliance/contracts/privacy/regulation, Product=features/roadmap/releases/UX, Supply Chain=logistics/inventory/vendors, General=everything else.

Return ONLY valid JSON — no markdown, no explanation:
2. KNOWLEDGE UNITS — atomic, self-contained statements an agent could act on alone.
3. RELATIONSHIPS — directed edges that form the company knowledge graph.

==================================================================================
UNIT KINDS — pick exactly one per unit
==================================================================================
  fact        – static factual info ("The billing API runs on AWS us-east-1.")
  process     – step-by-step how-to ("Deploy by merging to main, then tag v-prefix.")
  decision    – a choice made ("We chose Stripe over Adyen for v2 because of EU coverage.")
  ownership   – who owns/runs/maintains something ("Alice Chen owns billing-svc end-to-end.")
  definition  – what an internal term means ("P0 = customer-impacting outage.")
  policy      – a rule to follow ("All PRs require 2 reviewers before merge.")
  gotcha      – non-obvious tribal knowledge that bites people
                ("Webhook handler silently drops events when signature header missing.")

==================================================================================
DEPARTMENT TAGGING — every unit must carry exactly one department
==================================================================================
Pick the department most likely to *consume* this knowledge. Allowed values:
  engineering – code, infra, deploys, services, on-call
  product     – roadmap, features, user research, prioritization
  legal       – contracts, compliance, IP, NDAs, regulatory matters
  finance     – budgets, billing, revenue, accounting, payments policy
  hr          – hiring, onboarding, comp, performance, PTO, org chart
  sales       – pipeline, accounts, quotas, GTM motion
  marketing   – brand, campaigns, content, comms
  operations  – inventory, supply chain, logistics, vendor management, office
  security    – access control, secrets, vulnerabilities, audits, incident response
  general     – cross-cutting; pick this only when no single department fits

==================================================================================
RELATIONSHIP VERBS — use exactly these
==================================================================================
  owns | uses | requires | governs | manages | integrates-with | reports-to |
  defines | depends-on | replaces

==================================================================================
QUALITY RULES — non-negotiable
==================================================================================
A. ATOMIC. Each unit captures ONE claim. Split compound statements:
   BAD:  "Alice owns billing and Bob owns auth."
   GOOD: 1. "Alice Chen owns billing-svc."
         2. "Bob Martinez owns auth-svc."

B. SELF-CONTAINED. The statement must include the subject explicitly. No pronouns.
   BAD:  "owns billing"           (subject missing)
   BAD:  "She owns billing"        (pronoun)
   GOOD: "Alice Chen owns billing-svc."

C. EVIDENCE-BACKED. evidence_quote must be a LITERAL substring from the source text
   (copy-paste, no paraphrasing). If you can't find a literal substring, drop the unit.

D. CONFIDENCE ANCHORS:
   1.0  – Source states it directly and unambiguously.
   0.85 – Stated with one minor hedge ("seems", "I think").
   0.7  – Strongly implied, single source.
   0.5  – Inferred across multiple sentences.
   0.4  – Speculative. Omit anything below.

E. RELATIONSHIP RULES:
   - Both `from` and `to` must be entity names you also emit in `entities`.
   - Only emit a relationship if the verb is supported by the text.
   - For ownership transfers ("Bob took over from Alice"), emit:
       (Bob, owns, billing-svc)   — the new state
     and let the brain reconcile against any prior "Alice owns billing-svc".

F. SKIP NON-DURABLE NOISE: greetings, scheduling, "lgtm", "+1", chitchat, jokes.

G. TEMPORAL CUES: when the text says "as of", "took over", "previously", "no longer",
   "migrated from X to Y" — emit ONLY the current-state unit. The brain handles the
   supersession of the older fact.

==================================================================================
OUTPUT FORMAT — JSON only, no markdown fences, no preamble
==================================================================================
{
  "entities": [
    {"name": "string", "kind": "person|team|system|product|process|concept|tool|customer", "aliases": ["string"]}
  ],
  "units": [
    {
      "kind": "fact|process|decision|ownership|definition|policy|gotcha",
      "department": "engineering|product|legal|finance|hr|sales|marketing|operations|security|general",
      "subject": "string",
      "statement": "string (full sentence, includes subject, no pronouns)",
      "entities": ["string"],
      "evidence_quote": "string",
      "confidence": 0.0,
      "sector": "HR|Legal|Finance|Engineering|Product|Supply Chain|General"
      "evidence_quote": "literal substring from source",
      "confidence": 0.0
    }
  ],
  "relationships": [
    {"from": "entity_name", "relation": "verb", "to": "entity_name", "confidence": 0.0}
  ]
}

If the source contains no durable knowledge, return all three arrays empty."""

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

def _chunk_text(text: str, max_chars: int = 3500, overlap: int = 300) -> list[str]:
    """
    Split text into overlapping chunks that fit the model's context window.
    Each chunk is <= max_chars. Overlap carries context across boundaries.
    """
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                pos = text.rfind(sep, start + max_chars // 2, end)
                if pos != -1:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def _merge_extractions(results: list[dict]) -> dict:
    """Combine entity + unit + relationship lists from multiple chunk extractions."""
    seen_entities: set[str] = set()
    seen_stmts: set[str] = set()
    seen_rels: set[tuple] = set()
    entities, units, relationships = [], [], []

    for r in results:
        for e in r.get("entities", []):
            key = e.get("name", "").lower()
            if key and key not in seen_entities:
                seen_entities.add(key)
                entities.append(e)
        for u in r.get("units", []):
            key = u.get("statement", "").lower()[:80]
            if key and key not in seen_stmts:
                seen_stmts.add(key)
                units.append(u)
        for rel in r.get("relationships", []):
            key = (rel.get("from", ""), rel.get("relation", ""), rel.get("to", ""))
            if all(key) and key not in seen_rels:
                seen_rels.add(key)
                relationships.append(rel)

    return {"entities": entities, "units": units, "relationships": relationships}


class IngestionAgent:
    """Reads raw content (text or image) and extracts structured knowledge via the LLM."""

    def _extract_chunk(self, source_type: str, title: str, chunk: str, model_override: str | None = None) -> dict:
        prompt = (
            f"SOURCE TYPE: {source_type}\n"
            f"TITLE: {title}\n"
            f"---\n{chunk}\n---\n\n"
            "Extract entities, knowledge units, and relationships per the system instructions."
        )
        client, model = _resolve_override("extraction", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.1,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "extraction", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"chunk len={len(chunk)}",
            )
            return _parse_extraction_json(response.choices[0].message.content)
        except Exception as e:
            _log_call("extraction", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            print(f"[IngestionAgent] Chunk extraction error: {e}")
            return {"entities": [], "units": [], "relationships": []}

    def extract_from_text(self, source_type: str, title: str, content: str, model_override: str | None = None) -> dict:
        chunks = _chunk_text(content, max_chars=3500, overlap=300)
        if len(chunks) > 1:
            print(f"[IngestionAgent] Long content ({len(content)} chars) split into {len(chunks)} chunks")
        results = [self._extract_chunk(source_type, title, chunk, model_override=model_override) for chunk in chunks]
        merged = _merge_extractions(results)
        print(f"[IngestionAgent] Extracted {len(merged['units'])} units, "
              f"{len(merged['entities'])} entities, "
              f"{len(merged['relationships'])} relationships from {len(chunks)} chunk(s)")
        return merged

    def describe_image(self, image_data: bytes, mime_type: str = "image/png", model_override: str | None = None) -> str:
        """
        VLM step: convert an image to a rich text description suitable for RAG.
        Requires a vision-capable model at VLM_API_BASE.
        """
        b64 = base64.b64encode(image_data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"
        client, model = _resolve_override("vlm", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {
                            "type": "text",
                            "text": (
                                "You are the vision module of a Company Brain. Your description "
                                "feeds a downstream text extractor that will turn it into atomic "
                                "knowledge units. Be specific, named, and grounded.\n\n"
                                "Describe in plain prose (no lists, no markdown):\n"
                                "1. Every readable text element, transcribed verbatim where possible.\n"
                                "2. Every named system, service, person, team, or component shown.\n"
                                "3. Every visual relationship — arrows, containment, data flows, "
                                "deployment topology. Translate them into explicit sentences:\n"
                                "   • A box containing B → 'A includes B'.\n"
                                "   • Arrow from A to B labeled 'writes' → 'A writes to B'.\n"
                                "   • Dotted line → 'A optionally calls B'.\n"
                                "4. Any owner names, environments (prod/staging), regions, or versions.\n"
                                "5. Anything resembling a process step, decision, or policy.\n\n"
                                "Do NOT speculate beyond what is visible. Do NOT add a summary or "
                                "introduction. Start with the most important entity in the image."
                            ),
                        },
                    ],
                }],
                max_tokens=1024,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "vlm", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"image {len(image_data)} bytes",
            )
            return response.choices[0].message.content
        except Exception as e:
            _log_call("vlm", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            return f"[VLM description unavailable — configure VLM_API_BASE and VLM_MODEL_NAME. Error: {e}]"


RECONCILE_SYSTEM = """You reconcile a new knowledge unit against existing similar units from the company brain.

Verdicts:
  supersedes  – the new unit makes the existing one wrong or outdated (changed owner, updated policy, overriding decision, corrected fact). Mark the OLD unit as stale.
  duplicate   – both say effectively the same thing. Discard the new unit.
  independent – different enough to coexist. Keep both.

Do NOT mark supersedes for:
- Units about different entities even if the topic is similar (e.g. two different APIs deprecated at different times).
- Units where the new one adds detail the old one lacks — they are independent, not replacements.
- Units where timing is ambiguous (e.g. "we chose X" vs "we are evaluating X" — keep both).

Be conservative: only mark supersedes/duplicate when very confident. When in doubt, return independent.
Pick ONE of four verdicts:

  supersedes  – the NEW unit replaces the OLD one because it updates, corrects, or replaces it.
                Examples:
                  OLD: "Alice owns billing-svc"
                  NEW: "Bob and Nick took over billing-svc from Alice"
                  → supersedes (ownership transferred).

                  OLD: "We use Adyen for payments"
                  NEW: "We migrated from Adyen to Stripe"
                  → supersedes.

  duplicate   – both say effectively the same thing in different words. Drop the NEW one.
                Example:
                  OLD: "Bob and Nick took over billing"
                  NEW: "bob nick took over the billing"
                  → duplicate.

  conflicts   – both claim to be currently true but contradict each other and there is
                NO temporal cue showing which is newer. Keep both, flag as disputed.
                Example:
                  OLD (from Slack): "Alice owns billing-svc"
                  NEW (from Notion): "Bob owns billing-svc"
                  with no "took over" or date.
                  → conflicts.

  independent – different facts about possibly different subjects. Keep both.

Decision rules:
- If the NEW statement contains "took over", "replaced", "now owned by", "moved to",
  "no longer", "switched to", "as of", "previously" → likely supersedes.
- If two units make the same kind of claim about the same subject with different
  values and no temporal cue → conflicts.
- If statements just describe different aspects (one says "owns", another says "uses") → independent.

Return ONLY valid JSON (no markdown, no prose):
{"verdict": "supersedes"|"duplicate"|"conflicts"|"independent", "target_id": "<id>", "reason": "one sentence"}

target_id must be the id of the existing unit your verdict applies to."""


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
            # Query without a where filter to avoid ChromaDB errors when no docs
            # match the compound condition. We post-filter by kind and source_id.
            results = collection.query(
                query_texts=[new_unit["statement"]],
                n_results=min(6, total),
            )
        except Exception:
            return {"superseded_ids": [], "is_duplicate": False}

        ids = results["ids"][0] if results["ids"] else []
        distances = results["distances"][0] if results["distances"] else []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        # Post-filter: cosine distance < 0.30. Allow cross-kind (e.g. an
        # ownership statement may semantically supersede a fact). Allow
        # same-source (the LLM often emits old + new ownership in one chunk).
        candidates = [
            {
                "id": cid,
                "statement": doc,
                "kind": m.get("kind", ""),
                "subject": m.get("subject", ""),
                "distance": dist,
            }
            for cid, dist, doc, m in zip(ids, distances, docs, metas)
            if dist < 0.30 and cid != new_uid
        ]

        if not candidates:
            return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

        # Single LLM call covering all candidates
        candidates_text = "\n".join(
            f'  [{c["id"]}] (kind={c["kind"]}, similarity {1 - c["distance"]:.2f}) "{c["statement"]}"'
            for c in candidates
        )
        prompt = (
            f"NEW UNIT:\n"
            f'  kind: {new_unit["kind"]}\n'
            f'  subject: {new_unit["subject"]}\n'
            f'  statement: "{new_unit["statement"]}"\n\n'
            f"EXISTING SIMILAR UNITS:\n{candidates_text}\n\n"
            f"Pick the single most relevant existing unit. Apply the decision rules.\n"
            f'Return JSON with target_id set to the id of the matching existing unit.'
        )
        client, model = router.get("reconcile")
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": RECONCILE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=160,
                temperature=0.0,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(resp, "usage", None)
            result = _parse_extraction_json(resp.choices[0].message.content)
            verdict = result.get("verdict", "independent")
            target_id = result.get("target_id")
            _log_call(
                "reconcile", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"verdict={verdict}",
            )
            print(f"[Reconcile] verdict={verdict} target={target_id} reason={result.get('reason','')}")

            if verdict == "duplicate":
                return {"superseded_ids": [], "duplicate": True, "conflicts_with": []}
            if verdict == "supersedes" and target_id:
                return {"superseded_ids": [target_id], "duplicate": False, "conflicts_with": []}
            if verdict == "conflicts" and target_id:
                return {"superseded_ids": [], "duplicate": False, "conflicts_with": [target_id]}
        except Exception as e:
            _log_call("reconcile", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            print(f"[Reconcile] LLM error: {e}")

        return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

    def embed_and_store(
        self,
        source_id: str,
        source: dict,
        units: list,
        entities: list,
        relationships: list | None = None,
    ) -> dict:
        now = datetime.datetime.utcnow().isoformat() + "Z"

        # ── Step 1: build unit objects ──────────────────────────────────────
        # The LLM often splits subject ("Alice Chen") and statement ("owns
        # billing service") into separate fields. We normalize every statement
        # to be self-contained BEFORE writing to brain.json or ChromaDB so
        # that SKILLS.md, retrieval, and answers all use the complete sentence.
        def _normalize_statement(u: dict) -> str:
            stmt = u.get("statement", "").strip()
            subj = u.get("subject", "").strip()
            if subj and subj.lower() not in stmt.lower():
                return f"{subj} {stmt}"
            return stmt

        VALID_DEPTS = {"engineering", "product", "legal", "finance", "hr",
                       "sales", "marketing", "operations", "security", "general"}

        pending = []
        for u in units:
            uid = str(uuid.uuid4())[:10]
            dept = (u.get("department") or "general").strip().lower()
            if dept not in VALID_DEPTS:
                dept = "general"
            pending.append((uid, {
                "id": uid,
                "kind": u.get("kind", "fact"),
                "department": dept,
                "subject": u.get("subject", ""),
                "statement": _normalize_statement(u),  # always self-contained
                "entities": u.get("entities", []),
                "sector": u.get("sector", "General"),
                "evidence": [{"sourceId": source_id, "quote": u.get("evidence_quote", "")}],
                "confidence": float(u.get("confidence", 0.7)),
                "createdAt": now,
                "updatedAt": now,
            }))

        # ── Step 2: upsert all into ChromaDB first so reconciliation can query ──
        # The document text must be self-contained — prepend subject when the
        # LLM omitted it from the statement (e.g. "owns the billing service"
        # becomes "Alice Chen owns the billing service").
        def _full_text(unit: dict) -> str:
            stmt = unit.get("statement", "")
            subj = unit.get("subject", "")
            if subj and subj.lower() not in stmt.lower():
                return f"{subj} {stmt}"
            return stmt

        if pending:
            collection.upsert(
                ids=[uid for uid, _ in pending],
                documents=[_full_text(unit) for _, unit in pending],
                metadatas=[{
                    "source_id": source_id,
                    "kind": unit["kind"],
                    "subject": unit["subject"],
                    "confidence": unit["confidence"],
                    "entities": ",".join(unit.get("entities", [])),  # ChromaDB requires scalar
                    "sector": unit.get("sector", "General"),
                    "department": unit.get("department", "general"),
                } for _, unit in pending],
            )

        # ── Step 3: reconcile each new unit against existing ones ───────────
        superseded_ids: set[str] = set()
        stored_units = []
        # conflict pairs: target_existing_id -> set of new_unit_ids that conflict with it
        conflict_pairs: dict[str, set[str]] = {}

        for uid, unit in pending:
            rec = self._reconcile(unit, uid, source_id)
            if rec["duplicate"]:
                # Remove the just-upserted duplicate from ChromaDB
                try:
                    collection.delete(ids=[uid])
                except Exception:
                    pass
                continue
            superseded_ids.update(rec["superseded_ids"])
            for target_id in rec["conflicts_with"]:
                conflict_pairs.setdefault(target_id, set()).add(uid)
                # Mark the new unit as disputed and store back-reference
                unit["disputed"] = True
                unit.setdefault("conflictsWith", []).append(target_id)
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

        # Mark existing units as disputed when a new unit conflicts with them.
        disputed_count = 0
        for bu in brain["units"]:
            if bu["id"] in conflict_pairs:
                bu["disputed"] = True
                existing = set(bu.get("conflictsWith", []))
                existing.update(conflict_pairs[bu["id"]])
                bu["conflictsWith"] = list(existing)
                disputed_count += 1

        brain["units"] = stored_units + brain["units"]
        brain["sources"].insert(0, source)

        # ── Step 5: merge relationships into brain graph ───────────────────
        if not isinstance(brain.get("relationships"), list):
            brain["relationships"] = []

        new_rels = []
        first_unit_id = stored_units[0]["id"] if stored_units else "unknown"
        for r in (relationships or []):
            frm = r.get("from", "").strip()
            to = r.get("to", "").strip()
            rel = r.get("relation", "").strip()
            conf = float(r.get("confidence", 0.7))
            if not (frm and to and rel):
                continue
            # Deduplicate: skip if identical edge already in brain
            duplicate = any(
                x["from"] == frm and x["to"] == to and x["relation"] == rel
                for x in brain["relationships"]
            )
            if duplicate:
                continue
            edge = {
                "id": str(uuid.uuid4())[:8],
                "from": frm,
                "relation": rel,
                "to": to,
                "unitId": first_unit_id,
                "sourceId": source_id,
                "confidence": conf,
                "createdAt": now,
            }
            brain["relationships"].insert(0, edge)
            new_rels.append(edge)

        _write_brain(brain)
        _build_indexes(brain)

        return {
            "units_stored": len(stored_units),
            "units_superseded": superseded_count,
            "units_disputed": disputed_count,
            "entities_stored": len(new_entities),
            "relationships_stored": len(new_rels),
            "chroma_total": collection.count(),
            "brain_totals": {
                "sources": len(brain["sources"]),
                "entities": len(brain["entities"]),
                "units": len(brain["units"]),
                "relationships": len(brain["relationships"]),
            },
        }


class ExecutionAgent:
    """Semantic retrieval from ChromaDB + grounded generation via the 70B model."""

    def execute(self, query: str, n_results: int = 6, model_override: str | None = None) -> dict:
        t0 = time.time()

        count = collection.count()
        retrieved_ids, retrieved_docs, retrieved_metas = [], [], []

        if count > 0:
            # ── Signal 1: Dense (ChromaDB cosine) ─────────────────────────────
            dense_r = collection.query(
                query_texts=[query],
                n_results=min(n_results * 2, count),
            )
            dense_ids   = dense_r["ids"][0]
            dense_docs  = dense_r["documents"][0]
            dense_metas = dense_r["metadatas"][0]

            # ── Signal 2: BM25 sparse ─────────────────────────────────────────
            bm25_ranked: list[str] = []
            if _bm25_index and _bm25_unit_ids:
                bm25_scores = _bm25_index.get_scores(query.lower().split())
                bm25_ranked = [
                    uid for uid, sc in sorted(
                        zip(_bm25_unit_ids, bm25_scores), key=lambda x: x[1], reverse=True
                    )[:n_results * 2] if sc > 0
                ]

            # ── Signal 3: Entity index ────────────────────────────────────────
            entity_ranked: list[str] = []
            if _entity_index:
                q_tokens = set(query.lower().split())
                hits: dict[str, int] = {}
                for ent_key, uid_set in _entity_index.items():
                    overlap = len(set(ent_key.split()) & q_tokens)
                    if overlap:
                        for uid in uid_set:
                            hits[uid] = hits.get(uid, 0) + overlap
                entity_ranked = sorted(hits, key=lambda x: hits[x], reverse=True)[:n_results * 2]

            # ── RRF fusion ────────────────────────────────────────────────────
            fused_ids = _rrf_fuse([dense_ids, bm25_ranked, entity_ranked])[:n_results]

            # ── Resolve docs + metas for fused IDs ───────────────────────────
            dense_lookup = {
                uid: (doc, meta)
                for uid, doc, meta in zip(dense_ids, dense_docs, dense_metas)
            }
            bm25_pos = {uid: i for i, uid in enumerate(_bm25_unit_ids)}

            for uid in fused_ids:
                if uid in dense_lookup:
                    doc, meta = dense_lookup[uid]
                elif uid in bm25_pos:
                    doc  = _bm25_corpus[bm25_pos[uid]]
                    meta = {"kind": "fact", "confidence": 0.7, "subject": "", "sector": "General"}
                else:
                    continue
                retrieved_ids.append(uid)
                retrieved_docs.append(doc)
                retrieved_metas.append(meta)

        if retrieved_docs:
            context_blocks = [
                f"[{m.get('kind', 'fact')} | {m.get('subject', '')} | sector:{m.get('sector', 'General')} | conf:{m.get('confidence', 0.7):.2f}] {doc}"
                for doc, m in zip(retrieved_docs, retrieved_metas)
            ]
            context_section = "\n".join(context_blocks)
            # Pull disputed/stale flags from brain.json so the answer can flag conflicts.
            brain = _read_brain()
            unit_by_id = {u["id"]: u for u in brain.get("units", [])}

            context_lines = []
            disputed_facts = []
            for i, (uid, doc, m) in enumerate(
                zip(retrieved_ids, retrieved_docs, retrieved_metas), 1
            ):
                u = unit_by_id.get(uid, {})
                tags = []
                if u.get("disputed"):
                    tags.append("DISPUTED")
                    disputed_facts.append(i)
                if u.get("stale") or u.get("supersededBy"):
                    tags.append("SUPERSEDED")
                tag_str = f" [{', '.join(tags)}]" if tags else ""
                dept = m.get("department", "")
                dept_str = f" ({dept})" if dept and dept != "general" else ""
                context_lines.append(f"{i}.{tag_str}{dept_str} {doc}")
            context_section = "\n".join(context_lines)

            disputed_note = ""
            if disputed_facts:
                disputed_note = (
                    f"\nFacts {disputed_facts} are DISPUTED — multiple sources contradict. "
                    f"If your answer relies on them, explicitly call out the conflict.\n"
                )

            user_prompt = (
                f"Facts from the company knowledge base:\n"
                f"{context_section}\n{disputed_note}\n"
                f"Question: {query}\n"
                f"Answer:"
            )
            system_msg = (
                "You are a company knowledge assistant. Rules:\n"
                "1. Use ONLY the numbered facts above. Never invent names, services, or numbers.\n"
                "2. Always name the specific person, team, or system. Never say 'the company' "
                "or 'someone'.\n"
                "3. Prefer fresh facts; ignore facts marked SUPERSEDED unless the user explicitly "
                "asks about historical state.\n"
                "4. If facts are marked DISPUTED, say so plainly: "
                "\"The sources disagree — A says X, B says Y.\"\n"
                "5. If the facts do not answer the question, reply exactly: "
                "'The brain does not have this information yet.'\n"
                "6. Be brief. One to three sentences unless the user asks for detail."
            )
        else:
            user_prompt = f"Question: {query}"
            system_msg = (
                "The company brain has no knowledge ingested yet. "
                "Tell the user the brain is empty and they should ingest sources first."
            )

        client, model = _resolve_override("execute", model_override)
        t1 = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the BrainOS execution agent running on an AMD MI300X GPU. "
                        "Answer questions strictly based on company knowledge provided in context. "
                        "Never invent facts.\n\n"
                        "Format your response as:\n"
                        "1. A direct answer in 1-3 sentences.\n"
                        "2. A 'Sources:' bullet list citing each knowledge unit you used "
                        "(e.g. '- [policy] All PRs need 2 reviewers').\n"
                        "If the knowledge only partially covers the question, say explicitly "
                        "what is and is not covered."
                    ),
                },
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=512,
            temperature=0.1,
        )
        exec_latency_ms = int((time.time() - t1) * 1000)
        usage = getattr(response, "usage", None)
        _log_call(
            "execute", model, exec_latency_ms,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            note=f"q={query[:40]!r}",
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

    def evaluate(self, query: str, answer: str, context_docs: list, model_override: str | None = None) -> dict:
        if not context_docs:
            return {
                "confidence": 0.0,
                "grounded": False,
                "feedback": "No knowledge was retrieved — answer is not grounded in company data.",
            }

        ctx = "\n".join(f"{i+1}. {d}" for i, d in enumerate(context_docs))
        prompt = (
            f"You are auditing whether an answer is grounded in retrieved facts.\n\n"
            f"FACTS:\n{ctx}\n\n"
            f"QUESTION: {query}\n"
            f"ANSWER: {answer}\n\n"
            f"Evaluate whether the answer is grounded in the retrieved context.\n"
            f"Check: (1) Are all claims in the answer supported by the context? "
            f"(2) Does the answer cover ALL aspects of the question, or only some?\n"
            f"If the answer is only partially grounded or misses part of the question, "
            f"set grounded=false and explain what is missing in the feedback field.\n"
            f"Respond ONLY with JSON (no markdown):\n"
            f'{{ "confidence": 0.0-1.0, "grounded": true/false, "partial": true/false, "feedback": "one sentence" }}'
            f"Evaluate three things:\n"
            f"  1. ENTITY COVERAGE — every person/team/system named in the answer must "
            f"appear in the facts. If the answer names someone not in the facts → grounded=false.\n"
            f"  2. CLAIM SUPPORT — every claim in the answer must be derivable from the facts.\n"
            f"  3. SCOPE — the answer must address the question, not adjacent topics.\n\n"
            f"confidence guide:\n"
            f"  1.0 = every claim directly stated in facts.\n"
            f"  0.8 = answer is correct but minor inference not in facts.\n"
            f"  0.5 = partial support; some claim is unverifiable.\n"
            f"  0.2 = answer fabricates a name, number, or fact.\n"
            f"  0.0 = answer contradicts the facts or is unrelated.\n\n"
            f"Reply with JSON only (no markdown, no prose):\n"
            f'{{ "confidence": 0.0-1.0, "grounded": true/false, "feedback": "one sentence citing fact #s if relevant" }}'
        )
        client, model = _resolve_override("feedback", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=160,
                temperature=0.0,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            raw = response.choices[0].message.content.strip()
            parsed = _parse_extraction_json(raw)
            _log_call(
                "feedback", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"grounded={parsed.get('grounded', '?')}",
            )
            if "confidence" in parsed:
                return parsed
        except Exception as e:
            _log_call("feedback", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
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
    model: Optional[str] = None  # per-request override; falls back to routed default

class IngestRequest(BaseModel):
    kind: str
    title: str
    content: str
    url: Optional[str] = None
    model: Optional[str] = None  # per-request override for the extraction call


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/models")
def list_models():
    """
    Models available for per-request override on /ingest and /ask.
    Each entry tells the UI which endpoint serves the model so it can show a hint.
    """
    out = []
    for name, client in _MODEL_INDEX.items():
        out.append({
            "id": name,
            "endpoint": str(client.base_url),
            "is_text_default": name == MODEL_NAME,
            "is_vlm_default": name == VLM_MODEL_NAME,
        })
    out.sort(key=lambda m: (not m["is_text_default"], not m["is_vlm_default"], m["id"]))
    return {
        "models": out,
        "defaults": {
            "text": MODEL_NAME,
            "vlm": VLM_MODEL_NAME,
        },
    }


@app.get("/health")
def health_check():
    try:
        available_models = [m.id for m in llm_client.models.list().data]
    except Exception:
        available_models = []
    return {
        "status": "ok",
        "gpu_backend": "AMD MI300X via vLLM",
        "model": MODEL_NAME,
        "vlm_model": VLM_MODEL_NAME,
        "available_models": available_models,
        "chroma_units": collection.count(),
        "brain_json": os.path.exists(BRAIN_JSON),
    }


@app.post("/api/ingest")
def ingest_text(req: IngestRequest):
    source_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    extraction = ingest_agent.extract_from_text(
        req.kind, req.title, req.content, model_override=req.model,
    )

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
        relationships=extraction.get("relationships", []),
    )

    return {
        "message": "Ingested and structured via 70B model + ChromaDB.",
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
        **result,
    }


_MAX_EXTRACTION_CHARS = 12_000  # ~3k tokens; keeps prompt well inside 70B context window

def _extract_file_text(filename: str, data: bytes) -> str:
    """Extract plain text from PDF, TXT, MD, or CSV uploads."""
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            if not text.strip():
                return "[PDF has no selectable text — it may be a scanned/image-based PDF. Try the Image tab instead.]"
            return text
        except Exception as e:
            return f"[PDF extraction failed: {e}]"
    # TXT / MD / CSV — decode directly
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _chunk_text(text: str, chunk_size: int = _MAX_EXTRACTION_CHARS) -> list[str]:
    """Split text into chunks that fit inside the LLM context window."""
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
    return chunks or [text]


@app.post("/api/ingest_file")
async def ingest_file(
    title: str = Form(...),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """
    File upload pipeline:
      PDF/TXT/MD/CSV → text extraction → 70B extraction → ChromaDB → brain.json
    """
    data = await file.read()
    filename = file.filename or "upload"
    text = _extract_file_text(filename, data)

    if not text.strip() or text.startswith("[PDF has no selectable") or text.startswith("[PDF extraction failed"):
        raise HTTPException(status_code=422, detail=text if text.startswith("[") else "Could not extract any text from the file.")

    source_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Chunk large documents so each LLM call fits inside the context window,
    # then merge all extracted units + entities across chunks.
    chunks = _chunk_text(text)
    all_units: list[dict] = []
    all_entities: list[dict] = []
    for chunk in chunks:
        extraction = ingest_agent.extract_from_text(
            source_type=kind,
            title=title,
            content=chunk,
        )
        all_units.extend(extraction.get("units", []))
        all_entities.extend(extraction.get("entities", []))
    extraction = ingest_agent.extract_from_text(
        source_type=kind,
        title=title,
        content=text,
        model_override=model,
    )

    source = {
        "id": source_id,
        "kind": kind,
        "title": title,
        "content": text[:2000],  # store a preview, not the full text
        "url": url,
        "capturedAt": now,
        "uploadedFilename": filename,
        "charCount": len(text),
        "chunkCount": len(chunks),
    }

    result = struct_agent.embed_and_store(
        source_id=source_id,
        source=source,
        units=all_units,
        entities=all_entities,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
        relationships=extraction.get("relationships", []),
    )

    return {
        "message": f"File '{filename}' ingested ({len(chunks)} chunk(s)).",
        "chars_extracted": len(text),
        "chunks_processed": len(chunks),
        "source_id": source_id,
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
        **result,
    }


@app.post("/api/ingest_image")
async def ingest_image(
    title: str = Form(...),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),  # used as VLM model override
    text_model: Optional[str] = Form(None),  # used as extraction model override
    file: UploadFile = File(...),
):
    """
    VLM pipeline:
      image → VLM description → 70B extraction → ChromaDB embedding → brain.json
    """
    image_data = await file.read()
    mime = file.content_type or "image/png"

    # Step 1: VLM converts image to text
    description = ingest_agent.describe_image(image_data, mime, model_override=model)

    source_id = str(uuid.uuid4())[:8]
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Step 2: 70B model extracts entities + knowledge units from the description
    extraction = ingest_agent.extract_from_text(
        source_type=f"image/{kind}",
        title=title,
        content=description,
        model_override=text_model or model,
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
        relationships=extraction.get("relationships", []),
    )

    return {
        "message": "Image ingested via VLM → 70B extraction → ChromaDB.",
        "vlm_description_chars": len(description),
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
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
        item_title = item.get("title") or item.get("id", "Mock Source")
        extraction = ingest_agent.extract_from_text(
            source_type=item.get("source_type", "other"),
            title=item_title,
            content=item.get("content", ""),
        )
        source = {
            "id": source_id,
            "kind": item.get("source_type", "other"),
            "title": item_title,
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
    try:
        exec_result = exec_agent.execute(req.query)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")

    try:
        feedback = feedback_agent.evaluate(
            query=req.query,
            answer=exec_result["answer"],
            context_docs=exec_result["retrieved_docs"],
        )
    except Exception:
        feedback = {"confidence": 0.0, "grounded": False, "feedback": "Evaluation unavailable."}
    blocked = _is_sensitive(req.query)
    if blocked:
        return {
            "query": req.query,
            "answer": (
                f"This brain is configured to refuse questions touching '{blocked}'. "
                "Contact a brain administrator if you need this information."
            ),
            "used": [],
            "retrieved_texts": [],
            "latency_ms": 0,
            "feedback": {"confidence": 1.0, "grounded": True, "feedback": "Blocked by policy."},
            "blocked_topic": blocked,
        }
    exec_result = exec_agent.execute(req.query, model_override=req.model)
    feedback = feedback_agent.evaluate(
        query=req.query,
        answer=exec_result["answer"],
        context_docs=exec_result["retrieved_docs"],
        model_override=req.model,
    )

    return {
        "query": req.query,
        "answer": exec_result["answer"],
        "used": exec_result["retrieved_ids"],
        "retrieved_texts": exec_result["retrieved_docs"],  # actual sentences sent to the model
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
            key, val_str = m.group(1), m.group(2)
            try:
                # Accumulate labeled variants (e.g. request_success_total{reason="stop"}
                # and request_success_total{reason="abort"} both roll into one key).
                parsed[key] = parsed.get(key, 0.0) + float(val_str)
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
            "embedding_backend": EMBEDDING_BACKEND,
            "embedding_model": _embed_model,
            "chroma_units": collection.count(),
        },
        # Knowledge base
        "knowledge": {
            "sources": len(brain.get("sources", [])),
            "entities": len(brain.get("entities", [])),
            "units": len(brain.get("units", [])),
            "relationships": len(brain.get("relationships", [])),
            "stale_units": sum(1 for u in brain.get("units", []) if u.get("stale") or u.get("supersededBy")),
        },
        # VLM
        "vlm": {
            "model": VLM_MODEL_NAME,
            "endpoint": vlm_url,
        },
        # Per-task model routes (so the dashboard knows which model handles what)
        "routes": router.describe(),
        # Recent in-process LLM calls (last 80, newest last). Lets the dashboard
        # show real text-generation traffic — not just vLLM aggregates.
        "recent_calls": list(_call_log),
    }


@app.delete("/api/units/{unit_id}")
def delete_unit(unit_id: str):
    """Remove a single unit from ChromaDB and brain.json."""
    try:
        collection.delete(ids=[unit_id])
    except Exception as e:
        print(f"[delete_unit] ChromaDB delete skipped: {e}")

    brain = _read_brain()
    brain["units"] = [u for u in brain["units"] if u["id"] != unit_id]
    _write_brain(brain)
    return {"ok": True, "unit_id": unit_id}


# ── Security gates ────────────────────────────────────────────────────────────
# Simple env-driven guards. If EXPORT_TOKEN is unset, export is open. If set,
# /api/skills_export and SKILLS.md downloads require a matching ?token=...
# SENSITIVE_TOPICS is a comma-separated list of substrings. /api/ask refuses
# queries that match any of them. Both are intentionally low-tech for the demo.
EXPORT_TOKEN = os.getenv("EXPORT_TOKEN", "").strip()
SENSITIVE_TOPICS = [
    t.strip().lower() for t in os.getenv("SENSITIVE_TOPICS", "").split(",") if t.strip()
]


def _is_sensitive(query: str) -> str | None:
    """Return the matched topic if the query touches a sensitive subject."""
    q = query.lower()
    for topic in SENSITIVE_TOPICS:
        if topic and topic in q:
            return topic
    return None


@app.get("/api/skills_export")
def skills_export(token: str = ""):
    """Return brain state for SKILLS.md generation. Gated by EXPORT_TOKEN if set."""
    if EXPORT_TOKEN and token != EXPORT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing export token.")
    return _read_brain()


# ── Knowledge gap analysis ───────────────────────────────────────────────────
@app.post("/api/analyze/gaps")
def analyze_gaps():
    """
    Find structural holes in the knowledge graph:
      - Systems / products / teams without a documented owner.
      - Entities mentioned but never described in any unit.
      - Gotchas without a sibling process/policy.
      - Disputed units waiting for resolution.
    Cheap, deterministic, no LLM call. Run on demand.
    """
    brain = _read_brain()
    units = [u for u in brain.get("units", []) if not u.get("stale") and not u.get("supersededBy")]
    entities = brain.get("entities", [])
    rels = brain.get("relationships", [])

    gaps = []

    # 1. Systems/products/teams with no owner
    OWNER_VERBS = {"owns", "manages", "governs"}
    owned_targets = {r["to"].lower() for r in rels if r["relation"].lower() in OWNER_VERBS}
    for e in entities:
        if e["kind"] in ("system", "product", "team") and e["name"].lower() not in owned_targets:
            gaps.append({
                "severity": "high",
                "kind": "missing_owner",
                "entity": e["name"],
                "message": f"No documented owner for {e['kind']} '{e['name']}'.",
            })

    # 2. Entities mentioned in units but never described as a subject
    subjects = {u["subject"].lower() for u in units if u.get("subject")}
    mentioned = {n.lower() for u in units for n in u.get("entities", [])}
    for name in mentioned - subjects:
        # Skip if the entity appears as an owner target (already covered)
        if name and name not in owned_targets and len(name) > 2:
            ent = next((e for e in entities if e["name"].lower() == name), None)
            if ent:
                gaps.append({
                    "severity": "medium",
                    "kind": "undescribed_entity",
                    "entity": ent["name"],
                    "message": f"'{ent['name']}' is mentioned but no unit describes it directly.",
                })

    # 3. Gotchas with no neighbouring process/policy
    by_subject: dict[str, set[str]] = {}
    for u in units:
        s = u.get("subject", "").lower()
        if s:
            by_subject.setdefault(s, set()).add(u.get("kind", ""))
    for u in units:
        if u.get("kind") == "gotcha":
            kinds = by_subject.get(u.get("subject", "").lower(), set())
            if not (kinds & {"process", "policy"}):
                gaps.append({
                    "severity": "low",
                    "kind": "orphan_gotcha",
                    "entity": u.get("subject", ""),
                    "message": f"Gotcha about '{u.get('subject')}' has no documented process or policy.",
                })

    # 4. Open disputes
    for u in units:
        if u.get("disputed"):
            gaps.append({
                "severity": "high",
                "kind": "open_dispute",
                "entity": u.get("subject", ""),
                "message": f"Disputed claim about '{u.get('subject')}': {u.get('statement')}",
                "unitId": u["id"],
                "conflictsWith": u.get("conflictsWith", []),
            })

    # Sort: high → medium → low
    sev_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: sev_order.get(g["severity"], 3))

    return {
        "gaps": gaps,
        "counts": {
            "high": sum(1 for g in gaps if g["severity"] == "high"),
            "medium": sum(1 for g in gaps if g["severity"] == "medium"),
            "low": sum(1 for g in gaps if g["severity"] == "low"),
            "total": len(gaps),
        },
    }


@app.get("/api/state")
def get_state():
    """Return full brain state (sources, entities, units) for the Next.js frontend."""
    return _read_brain()


@app.delete("/api/units/{unit_id}")
def delete_unit(unit_id: str):
    """Mark a single unit as stale (soft delete) and remove it from ChromaDB."""
    brain = _read_brain()
    found = False
    for u in brain["units"]:
        if u["id"] == unit_id:
            u["stale"] = True
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")
    _write_brain(brain)
    try:
        collection.delete(ids=[unit_id])
    except Exception:
        pass
    return {"ok": True, "deleted": unit_id}


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
    _write_brain({"sources": [], "entities": [], "units": [], "relationships": []})
    return {"ok": True, "cleared": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081, reload=False)
