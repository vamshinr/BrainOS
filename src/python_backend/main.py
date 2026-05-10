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
import zipfile
import tempfile
import subprocess
import shutil
import xml.etree.ElementTree as ET
from types import SimpleNamespace
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from rank_bm25 import BM25Okapi
from pypdf import PdfReader
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

# ── vLLM HTTP client ───────────────────────────────────────────────────────────
# Talks directly to the vLLM server's HTTP API on the AMD MI300X via httpx.
def _to_obj(data):
    """Recursively convert JSON dicts to SimpleNamespace so callers can use
    attribute access (response.choices[0].message.content, etc.)."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: _to_obj(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_to_obj(v) for v in data]
    return data


class _ChatCompletions:
    def __init__(self, http: httpx.Client):
        self._http = http

    def create(self, *, model, messages, max_tokens=None, temperature=None, **kwargs):
        payload = {"model": model, "messages": messages, **kwargs}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        r = self._http.post("/chat/completions", json=payload)
        r.raise_for_status()
        return _to_obj(r.json())


class _Chat:
    def __init__(self, http: httpx.Client):
        self.completions = _ChatCompletions(http)


class _Embeddings:
    def __init__(self, http: httpx.Client):
        self._http = http

    def create(self, *, model, input):
        r = self._http.post("/embeddings", json={"model": model, "input": input})
        r.raise_for_status()
        return _to_obj(r.json())


class _Models:
    def __init__(self, http: httpx.Client):
        self._http = http

    def list(self):
        r = self._http.get("/models")
        r.raise_for_status()
        return _to_obj(r.json())


class VLLMClient:
    def __init__(self, base_url: str, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.chat = _Chat(self._http)
        self.embeddings = _Embeddings(self._http)
        self.models = _Models(self._http)


# ── LLM clients (vLLM HTTP, pointed at AMD MI300X) ─────────────────────────────
vllm_url = os.getenv("VLLM_API_BASE", "http://134.199.204.211:8000/v1")
vlm_url = os.getenv("VLM_API_BASE", vllm_url)

llm_client = VLLMClient(base_url=vllm_url)
vlm_client = VLLMClient(base_url=vlm_url)


def _resolve_model(client: VLLMClient, env_name: str, env_value: str) -> str:
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
        self._client_cache: dict[str, VLLMClient] = {
            vllm_url: llm_client,
            vlm_url: vlm_client,
        }
        self._routes: dict[str, tuple[VLLMClient, str]] = {}
        for task in TASKS:
            self._routes[task] = self._resolve(task)

    def _resolve(self, task: str) -> tuple[VLLMClient, str]:
        tu = task.upper()
        # VLM has historic env var names
        if task == "vlm":
            return vlm_client, VLM_MODEL_NAME
        api_base = os.getenv(f"{tu}_API_BASE", "").strip() or vllm_url
        model = os.getenv(f"{tu}_MODEL", "").strip() or MODEL_NAME
        if api_base not in self._client_cache:
            self._client_cache[api_base] = VLLMClient(base_url=api_base)
        return self._client_cache[api_base], model

    def get(self, task: str) -> tuple[VLLMClient, str]:
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
# → which vLLM client serves it. Used by the per-request override path so
# the dropdown on /ingest and /ask can show every reachable model.
def _build_model_index() -> dict[str, VLLMClient]:
    index: dict[str, VLLMClient] = {}
    seen_endpoints: set[str] = set()

    def _add(client: VLLMClient):
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


_MODEL_INDEX: dict[str, VLLMClient] = _build_model_index()
print(f"[BrainOS] Available models for per-request override: {sorted(_MODEL_INDEX.keys())}")


def _resolve_override(task: str, model_override: str | None) -> tuple[VLLMClient, str]:
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


def _resolve_text_override(task: str, model_override: str | None) -> tuple[VLLMClient, str]:
    requested_client = _MODEL_INDEX.get(model_override) if model_override else None
    default_client, default_model = router.get(task)
    if model_override and (
        (model_override == VLM_MODEL_NAME and model_override != default_model)
        or (requested_client is vlm_client and requested_client is not default_client)
    ):
        _debug_event(
            "model.override.ignored",
            "Ignoring vision model override for text extraction",
            task=task,
            requested=model_override,
            fallback=default_model,
        )
        return default_client, default_model
    client, model = _resolve_override(task, model_override)
    _debug_event(
        "model.route.text",
        "Resolved text-capable model route",
        task=task,
        requested=model_override,
        model=model,
    )
    return client, model


# ── Recent-calls log (in-memory ring buffer, surfaced to the dashboard) ──────
_call_log: collections.deque = collections.deque(maxlen=80)
_call_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _debug_value(value) -> str:
    if isinstance(value, str):
        value = value.replace("\n", "\\n")
        if len(value) > 140:
            value = value[:137] + "..."
    return str(value)


def _debug_event(stage: str, message: str, **fields):
    details = " | ".join(
        f"{key}={_debug_value(value)}" for key, value in fields.items()
        if value is not None
    )
    suffix = f" | {details}" if details else ""
    print(f"[BrainOS][{_utc_now_iso()}][{stage}] {message}{suffix}")


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
            "ts": _utc_now_iso(),
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
    Calls vLLM's /v1/embeddings endpoint on the AMD MI300X GPU.
    Requires a dedicated embedding model served via vLLM (e.g. BAAI/bge-large-en-v1.5).
    """
    def __init__(self, base_url: str, model: str):
        self._client = VLLMClient(base_url=base_url)
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        texts = [t if isinstance(t, str) else t.decode("utf-8", errors="replace") for t in input]
        response = self._client.embeddings.create(model=self._model, input=texts)
        return [e.embedding for e in response.data]


if _embed_api_base:
    embedding_fn = VLLMEmbeddingFunction(
        base_url=_embed_api_base,
        model=_embed_model,
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
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("sources", [])
    state.setdefault("entities", [])
    state.setdefault("units", [])
    state.setdefault("relationships", [])
    state.setdefault("rawChunks", [])
    return state

def _write_brain(state: dict):
    with _json_lock:
        with open(BRAIN_JSON, "w") as f:
            json.dump(state, f, indent=2)

# ── In-memory BM25 + entity indexes ───────────────────────────────────────────
_bm25_index: object = None           # BM25Okapi instance (None until first ingest)
_bm25_unit_ids: list[str] = []       # parallel to _bm25_corpus
_bm25_corpus: list[str] = []         # searchable unit text
_chunk_bm25_index: object = None     # BM25Okapi over raw source chunks
_chunk_ids: list[str] = []           # parallel to _chunk_corpus
_chunk_corpus: list[str] = []        # searchable raw chunk text
_entity_index: dict[str, set[str]] = {}  # entity_name_lower → {unit_id, ...}


def _tokenize_search(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_.:/-]*", text.lower())


def _unit_search_text(unit: dict) -> str:
    evidence = " ".join(
        e.get("quote", "") for e in unit.get("evidence", [])
        if isinstance(e, dict)
    )
    temporal = " ".join(str(unit.get(k, "")) for k in (
        "validFrom", "validTo", "effectiveDate", "observedAt", "supersededAt", "temporalStatus",
    ))
    return " ".join([
        unit.get("statement", ""),
        unit.get("subject", ""),
        unit.get("kind", ""),
        unit.get("department", ""),
        unit.get("sector", ""),
        temporal,
        " ".join(unit.get("entities", [])),
        evidence,
    ])


_ENTITY_TOKEN_RE = re.compile(
    r"(?:\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b|/[a-z0-9][a-z0-9_./:-]*|\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b|\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2}\b)"
)


def _fallback_entities_from_text(text: str) -> list[str]:
    """Best-effort retrieval aliases from raw text; these are not asserted facts."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _ENTITY_TOKEN_RE.findall(text or ""):
        value = match.strip(".,;:()[]{}'\"")
        if len(value) < 3:
            continue
        if value.lower() in {
            "the", "and", "or", "but", "for", "with", "from", "this", "that",
            "when", "then", "before", "after", "source", "title",
        }:
            continue
        key = value.lower()
        if key not in seen:
            seen.add(key)
            found.append(value)
    return found[:80]


def _build_indexes(brain: dict):
    """Rebuild BM25 + entity indexes from brain state. Called on startup and after every ingest."""
    global _bm25_index, _bm25_unit_ids, _bm25_corpus, _chunk_bm25_index, _chunk_ids, _chunk_corpus, _entity_index
    indexable = [u for u in brain.get("units", []) if u.get("id")]
    _bm25_unit_ids = [u["id"] for u in indexable]
    _bm25_corpus   = [_unit_search_text(u) for u in indexable]
    tokenized      = [_tokenize_search(stmt) for stmt in _bm25_corpus]
    _bm25_index    = BM25Okapi(tokenized) if tokenized else None

    chunks = [c for c in brain.get("rawChunks", []) if c.get("id") and c.get("text")]
    _chunk_ids = [c["id"] for c in chunks]
    _chunk_corpus = [c.get("text", "") for c in chunks]
    chunk_tokenized = [_tokenize_search(text) for text in _chunk_corpus]
    _chunk_bm25_index = BM25Okapi(chunk_tokenized) if chunk_tokenized else None

    _entity_index  = {}
    for u in indexable:
        subject = u.get("subject", "").lower().strip()
        if subject:
            _entity_index.setdefault(subject, set()).add(u["id"])
        for ent in u.get("entities", []):
            key = ent.lower().strip()
            if key:
                _entity_index.setdefault(key, set()).add(u["id"])
        for alias in _fallback_entities_from_text(_unit_search_text(u)):
            key = alias.lower().strip()
            if key:
                _entity_index.setdefault(key, set()).add(u["id"])

def _rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion — combines ranked lists of unit IDs without weight tuning."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, uid in enumerate(ranked):
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


_TEMPORAL_STATUSES = {"current", "future", "expired", "historical", "unknown"}


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalize_date(value: str | None) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _today_utc() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _infer_temporal_status(unit: dict, source: dict | None = None) -> str:
    today = _today_utc()
    status = str(unit.get("temporal_status") or unit.get("temporalStatus") or "").strip().lower()
    if status in _TEMPORAL_STATUSES:
        return status

    valid_from = _parse_date(unit.get("valid_from") or unit.get("validFrom"))
    valid_to = _parse_date(unit.get("valid_to") or unit.get("validTo"))
    effective = _parse_date(unit.get("effective_date") or unit.get("effectiveDate"))
    observed = _parse_date(unit.get("observed_at") or unit.get("observedAt"))

    if valid_to and valid_to < today:
        return "expired"
    if effective and effective > today:
        return "future"
    if valid_from and valid_from > today:
        return "future"
    if valid_to or valid_from or effective or observed:
        return "current"
    if source and _parse_date(source.get("capturedAt")):
        return "unknown"
    return "unknown"


def _temporal_fields(unit: dict, source: dict | None = None) -> dict:
    observed = (
        _normalize_date(unit.get("observed_at") or unit.get("observedAt"))
        or _normalize_date(source.get("capturedAt") if source else None)
    )
    fields = {
        "validFrom": _normalize_date(unit.get("valid_from") or unit.get("validFrom")),
        "validTo": _normalize_date(unit.get("valid_to") or unit.get("validTo")),
        "effectiveDate": _normalize_date(unit.get("effective_date") or unit.get("effectiveDate")),
        "observedAt": observed,
        "temporalStatus": _infer_temporal_status(unit, source),
    }
    return {k: v for k, v in fields.items() if v}


def _detect_temporal_intent(query: str) -> dict:
    q = query.lower()
    if re.search(r"\b(now|current|currently|today|latest|active)\b", q):
        return {"mode": "current", "target_date": _today_utc().isoformat()}
    if re.search(r"\b(after|from|starting|effective)\b", q):
        mode = "future"
    elif re.search(r"\b(before|previously|past|historical|history|old|q[1-4])\b", q):
        mode = "historical"
    else:
        mode = "general"

    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", q)
    target_date = date_match.group(1) if date_match else None
    if not target_date:
        month_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b",
            q,
        )
        if month_match:
            month = [
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december",
            ].index(month_match.group(1)) + 1
            target_date = datetime.date(int(month_match.group(2)), month, 1).isoformat()
    if target_date and mode == "general":
        mode = "date"
    return {"mode": mode, "target_date": target_date}


def _unit_temporal_score(unit: dict, intent: dict) -> float:
    mode = intent.get("mode", "general")
    status = unit.get("temporalStatus", "unknown")
    target_date = _parse_date(intent.get("target_date"))
    valid_from = _parse_date(unit.get("validFrom"))
    valid_to = _parse_date(unit.get("validTo"))
    effective = _parse_date(unit.get("effectiveDate"))

    if target_date:
        start = effective or valid_from
        end = valid_to
        if start and start > target_date:
            return 0.7 if mode == "future" else 0.65
        if end and end < target_date:
            return 1.15 if mode == "historical" else 0.75
        if (not start or start <= target_date) and (not end or target_date <= end):
            return 1.35

    if mode == "current":
        return {"current": 1.35, "unknown": 1.0, "future": 0.65, "historical": 0.55, "expired": 0.45}.get(status, 1.0)
    if mode == "future":
        return {"future": 1.4, "current": 1.0, "unknown": 0.9, "historical": 0.55, "expired": 0.5}.get(status, 1.0)
    if mode == "historical":
        return {"historical": 1.35, "expired": 1.25, "current": 0.9, "unknown": 0.85, "future": 0.45}.get(status, 1.0)
    return {"current": 1.1, "unknown": 1.0, "future": 0.95, "historical": 0.85, "expired": 0.75}.get(status, 1.0)

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

G. TEMPORAL CUES: preserve time instead of flattening it.
   - If the text says "as of", "effective", "starts", "until", "through",
     "previously", "no longer", "deprecated by", "after", "before", or gives
     a quarter/month/date, emit the relevant temporal fields.
   - Do NOT collapse future facts into current facts. Example:
       "Bob takes over billing-svc effective 2026-06-01"
       means Bob's ownership is future until that date.
   - Do NOT delete historical state. Example:
       "Alice owns billing-svc until 2026-06-01" is a valid dated fact.
   - Use ISO dates (YYYY-MM-DD) whenever the source provides enough information.
   - If the source says "next month" or "last Tuesday", infer from the source date
     only when obvious; otherwise leave the date empty and set temporal_status unknown.

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
      "sector": "HR|Legal|Finance|Engineering|Product|Supply Chain|General",
      "valid_from": "YYYY-MM-DD or empty",
      "valid_to": "YYYY-MM-DD or empty",
      "effective_date": "YYYY-MM-DD or empty",
      "observed_at": "YYYY-MM-DD or empty",
      "temporal_status": "current|future|expired|historical|unknown"
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
        return {"entities": [], "units": [], "relationships": []}


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

    def _extract_chunk(
        self,
        source_type: str,
        title: str,
        chunk: str,
        model_override: str | None = None,
        *,
        retry: bool = False,
    ) -> dict:
        retry_instructions = ""
        if retry:
            retry_instructions = (
                "\n\nThe previous pass returned no durable knowledge. Re-read carefully and "
                "extract operational facts, named services, owners, unsafe windows, APIs, "
                "policies, gotchas, dates, teams, tools, and relationships. Return empty "
                "arrays only if this chunk truly contains no company knowledge."
            )
        prompt = (
            f"SOURCE TYPE: {source_type}\n"
            f"TITLE: {title}\n"
            f"---\n{chunk}\n---\n\n"
            "Extract entities, knowledge units, and relationships per the system instructions."
            f"{retry_instructions}"
        )
        client, model = _resolve_text_override("extraction", model_override)
        t0 = time.time()
        _debug_event(
            "extract.chunk.start",
            "Sending chunk to extraction model",
            source_type=source_type,
            title=title,
            model=model,
            chars=len(chunk),
            retry=retry,
        )
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
            parsed = _parse_extraction_json(response.choices[0].message.content)
            parsed.setdefault("entities", [])
            parsed.setdefault("units", [])
            parsed.setdefault("relationships", [])
            _debug_event(
                "extract.chunk.done",
                "Extraction model returned structured data",
                model=model,
                latency_ms=latency_ms,
                units=len(parsed.get("units", [])),
                entities=len(parsed.get("entities", [])),
                relationships=len(parsed.get("relationships", [])),
                retry=retry,
            )
            return parsed
        except Exception as e:
            _log_call("extraction", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            _debug_event(
                "extract.chunk.error",
                "Extraction model failed",
                model=model,
                latency_ms=int((time.time() - t0) * 1000),
                error=e,
            )
            return {"entities": [], "units": [], "relationships": []}

    def extract_from_text(self, source_type: str, title: str, content: str, model_override: str | None = None) -> dict:
        _debug_event(
            "extract.text.start",
            "Preparing text for extraction",
            source_type=source_type,
            title=title,
            chars=len(content),
            model_override=model_override,
        )
        chunks = _chunk_text(content, max_chars=3500, overlap=300)
        _debug_event(
            "extract.text.chunks",
            "Text chunking complete",
            source_type=source_type,
            chunks=len(chunks),
            chunk_chars=",".join(str(len(chunk)) for chunk in chunks),
        )
        results = []
        for idx, chunk in enumerate(chunks, start=1):
            result = self._extract_chunk(source_type, title, chunk, model_override=model_override)
            empty_result = not (
                result.get("units") or result.get("entities") or result.get("relationships")
            )
            if empty_result and len(chunk.strip()) >= 800:
                _debug_event(
                    "extract.chunk.retry",
                    "Retrying extraction because a substantial chunk returned no knowledge",
                    source_type=source_type,
                    title=title,
                    chunk=idx,
                    chars=len(chunk),
                )
                retry_result = self._extract_chunk(
                    source_type,
                    title,
                    chunk,
                    model_override=model_override,
                    retry=True,
                )
                if retry_result.get("units") or retry_result.get("entities") or retry_result.get("relationships"):
                    result = retry_result
            results.append(result)
        merged = _merge_extractions(results)
        _debug_event(
            "extract.text.done",
            "Merged extraction results",
            source_type=source_type,
            chunks=len(chunks),
            units=len(merged["units"]),
            entities=len(merged["entities"]),
            relationships=len(merged["relationships"]),
        )
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
        _debug_event(
            "image.describe.start",
            "Sending image to vision model",
            mime_type=mime_type,
            bytes=len(image_data),
            model=model,
        )
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
            description = response.choices[0].message.content
            _debug_event(
                "image.describe.done",
                "Vision model returned description",
                model=model,
                latency_ms=latency_ms,
                chars=len(description or ""),
            )
            return description
        except Exception as e:
            _log_call("vlm", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            _debug_event(
                "image.describe.error",
                "Vision model failed",
                model=model,
                latency_ms=int((time.time() - t0) * 1000),
                error=e,
            )
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
            return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

        try:
            # Query without a where filter to avoid ChromaDB errors when no docs
            # match the compound condition. We post-filter by kind and source_id.
            results = collection.query(
                query_texts=[new_unit["statement"]],
                n_results=min(6, total),
            )
        except Exception:
            return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

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
            if dist < 0.30 and cid != new_uid and (m or {}).get("doc_type", "unit") == "unit"
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
        raw_chunks: list[str] | None = None,
    ) -> dict:
        now = _utc_now_iso()
        _debug_event(
            "store.start",
            "Preparing extracted data for storage",
            source_id=source_id,
            source_kind=source.get("kind"),
            units_in=len(units),
            entities_in=len(entities),
            relationships_in=len(relationships or []),
            raw_chunks=len(raw_chunks or []),
        )

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
            temporal = _temporal_fields(u, source)
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
                **temporal,
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
            _debug_event(
                "store.chroma.upsert",
                "Upserting units into ChromaDB",
                source_id=source_id,
                pending_units=len(pending),
            )
            collection.upsert(
                ids=[uid for uid, _ in pending],
                documents=[_full_text(unit) for _, unit in pending],
                metadatas=[{
                    "doc_type": "unit",
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
            if unit.get("temporalStatus") == "future":
                unit["pendingSupersedes"] = rec["superseded_ids"]
            else:
                superseded_ids.update(rec["superseded_ids"])
            for target_id in rec["conflicts_with"]:
                conflict_pairs.setdefault(target_id, set()).add(uid)
                # Mark the new unit as disputed and store back-reference
                unit["disputed"] = True
                unit.setdefault("conflictsWith", []).append(target_id)
            stored_units.append(unit)

        _debug_event(
            "store.reconcile.done",
            "Reconciliation complete",
            source_id=source_id,
            pending_units=len(pending),
            stored_units=len(stored_units),
            superseded=len(superseded_ids),
            conflict_targets=len(conflict_pairs),
        )

        # ── Step 4: merge into brain.json ───────────────────────────────────
        brain = _read_brain()

        if not isinstance(brain.get("rawChunks"), list):
            brain["rawChunks"] = []
        new_raw_chunks = []
        for idx, chunk in enumerate(raw_chunks or [], start=1):
            text = (chunk or "").strip()
            if not text:
                continue
            chunk_id = f"{source_id}:chunk:{idx}"
            entry = {
                "id": chunk_id,
                "sourceId": source_id,
                "sourceTitle": source.get("title", ""),
                "kind": source.get("kind", "doc"),
                "chunkIndex": idx,
                "text": text[:6000],
                "charCount": len(text),
                "createdAt": now,
            }
            brain["rawChunks"].insert(0, entry)
            new_raw_chunks.append(entry)

        if new_raw_chunks:
            _debug_event(
                "store.chroma.raw_chunks",
                "Upserting raw source chunks into ChromaDB",
                source_id=source_id,
                raw_chunks=len(new_raw_chunks),
            )
            collection.upsert(
                ids=[chunk["id"] for chunk in new_raw_chunks],
                documents=[chunk["text"] for chunk in new_raw_chunks],
                metadatas=[{
                    "doc_type": "raw_chunk",
                    "source_id": source_id,
                    "source_title": chunk.get("sourceTitle", ""),
                    "kind": chunk.get("kind", "doc"),
                    "chunk_index": chunk.get("chunkIndex", 0),
                } for chunk in new_raw_chunks],
            )

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
                bu["supersededAt"] = now
                if not bu.get("validTo"):
                    bu["validTo"] = now[:10]
                bu["temporalStatus"] = "historical"
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

        _debug_event(
            "store.done",
            "Brain state written and indexes rebuilt",
            source_id=source_id,
            units_stored=len(stored_units),
            entities_stored=len(new_entities),
            relationships_stored=len(new_rels),
            raw_chunks_stored=len(new_raw_chunks),
            chroma_total=collection.count(),
            brain_sources=len(brain["sources"]),
            brain_units=len(brain["units"]),
            brain_raw_chunks=len(brain.get("rawChunks", [])),
        )

        return {
            "units_stored": len(stored_units),
            "units_superseded": superseded_count,
            "units_disputed": disputed_count,
            "entities_stored": len(new_entities),
            "relationships_stored": len(new_rels),
            "raw_chunks_stored": len(new_raw_chunks),
            "chroma_total": collection.count(),
            "brain_totals": {
                "sources": len(brain["sources"]),
                "entities": len(brain["entities"]),
                "units": len(brain["units"]),
                "relationships": len(brain["relationships"]),
                "rawChunks": len(brain.get("rawChunks", [])),
            },
        }


class ExecutionAgent:
    """Hybrid retrieval over ChromaDB, BM25, raw chunks, and brain.json graph state."""

    def revise_answer(
        self,
        query: str,
        draft_answer: str,
        context_docs: list,
        verification: dict,
        model_override: str | None = None,
    ) -> str:
        """Rewrite an answer after verifier finds unsupported or weakly grounded claims."""
        if not context_docs:
            return "The brain does not have this information yet."

        ctx = "\n".join(f"{i+1}. {d}" for i, d in enumerate(context_docs))
        unsupported = verification.get("unsupported_claims") or []
        contradictions = verification.get("contradictions") or []
        missing = verification.get("missing_aspects") or []
        prompt = (
            "Rewrite the draft answer so it is strictly supported by the retrieved context.\n\n"
            "Rules:\n"
            "1. Remove every unsupported or contradicted claim.\n"
            "2. Do not add any new names, causes, timelines, tools, services, or process details.\n"
            "3. For WHY/root-cause questions, separate directly stated causes from unknowns. "
            "Use 'The retrieved evidence states...' or 'The retrieved evidence does not explicitly state...' when needed.\n"
            "4. Cite every concrete claim with context item IDs like [1] or [2].\n"
            "5. If only raw chunks support the answer, say 'Based on source excerpt context...'.\n"
            "6. If the context is insufficient, answer exactly: 'The brain does not have this information yet.'\n"
            "7. Keep the final answer concise.\n\n"
            f"QUESTION:\n{query}\n\n"
            f"RETRIEVED CONTEXT:\n{ctx}\n\n"
            f"DRAFT ANSWER:\n{draft_answer}\n\n"
            f"UNSUPPORTED CLAIMS TO REMOVE:\n{json.dumps(unsupported)}\n\n"
            f"CONTRADICTIONS TO AVOID:\n{json.dumps(contradictions)}\n\n"
            f"MISSING ASPECTS TO ACKNOWLEDGE IF RELEVANT:\n{json.dumps(missing)}\n\n"
            "Return only the revised final answer. No JSON."
        )
        client, model = _resolve_override("execute", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an evidence-constrained answer rewriter. "
                            "Your only job is to remove unsupported content and produce a concise, cited answer."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=420,
                temperature=0.0,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "execute", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note="answer_revision",
            )
            revised = response.choices[0].message.content.strip()
            _debug_event(
                "answer.revise.done",
                "Verifier-triggered answer revision complete",
                unsupported=len(unsupported),
                contradictions=len(contradictions),
                missing=len(missing),
            )
            return revised or "The brain does not have this information yet."
        except Exception as e:
            _debug_event("answer.revise.error", "Answer revision failed", error=e)
            return draft_answer

    def execute(self, query: str, n_results: int = 6, model_override: str | None = None) -> dict:
        t0 = time.time()

        brain = _read_brain()
        searchable_units = [u for u in brain.get("units", []) if u.get("id")]
        raw_chunks = [c for c in brain.get("rawChunks", []) if c.get("id") and c.get("text")]
        unit_by_id = {u["id"]: u for u in searchable_units}
        chunk_by_id = {c["id"]: c for c in raw_chunks}
        temporal_intent = _detect_temporal_intent(query)
        _build_indexes(brain)

        retrieved_ids: list[str] = []
        retrieved_docs: list[str] = []
        retrieved_metas: list[dict] = []
        retrieved_chunk_ids: list[str] = []
        retrieved_chunks: list[dict] = []
        relationship_context: list[str] = []

        query_tokens = _tokenize_search(query)
        debug = {
            "retrieval_mode": "hybrid_bm25_vector_graph",
            "temporal_intent": temporal_intent,
            "vector_unit_hits": [],
            "vector_chunk_hits": [],
            "bm25_hits": [],
            "chunk_bm25_hits": [],
            "entity_hits": [],
            "graph_hits": [],
            "final_unit_ids": [],
            "final_chunk_ids": [],
        }

        def _dedupe_ranked(ids: list[str], limit: int | None = None) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for item_id in ids:
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    out.append(item_id)
                    if limit and len(out) >= limit:
                        break
            return out

        def _rank_debug(ids: list[str], scores: dict[str, float] | None = None, limit: int = 12) -> list[dict]:
            return [
                {"id": item_id, "score": round(float(scores.get(item_id, 0.0)), 4) if scores else None}
                for item_id in ids[:limit]
            ]

        # ── Signal 1: Chroma vector search over units + raw chunks ───────────
        vector_unit_ranked: list[str] = []
        vector_chunk_ranked: list[str] = []
        vector_unit_scores: dict[str, float] = {}
        vector_chunk_scores: dict[str, float] = {}
        chroma_total = collection.count()
        if chroma_total > 0:
            try:
                vector_results = collection.query(
                    query_texts=[query],
                    n_results=min(max(n_results * 8, 24), chroma_total),
                )
                ids = vector_results["ids"][0] if vector_results.get("ids") else []
                distances = vector_results["distances"][0] if vector_results.get("distances") else []
                metas = vector_results["metadatas"][0] if vector_results.get("metadatas") else []
                for cid, dist, meta in zip(ids, distances, metas):
                    doc_type = (meta or {}).get("doc_type", "unit")
                    similarity = max(0.0, 1.0 - float(dist or 0.0))
                    if doc_type == "raw_chunk" or cid in chunk_by_id:
                        if cid in chunk_by_id:
                            vector_chunk_ranked.append(cid)
                            vector_chunk_scores[cid] = similarity
                    else:
                        if cid in unit_by_id:
                            vector_unit_ranked.append(cid)
                            vector_unit_scores[cid] = similarity
                vector_unit_ranked = _dedupe_ranked(vector_unit_ranked, n_results * 6)
                vector_chunk_ranked = _dedupe_ranked(vector_chunk_ranked, n_results * 4)
                _debug_event(
                    "retrieve.chroma",
                    "Chroma vector query complete",
                    query=query,
                    total=chroma_total,
                    unit_hits=len(vector_unit_ranked),
                    chunk_hits=len(vector_chunk_ranked),
                )
            except Exception as e:
                _debug_event("retrieve.chroma.error", "Chroma vector query failed", query=query, error=e)

        # ── Signal 2: lexical BM25 over enriched unit text ──────────────────
        bm25_ranked: list[str] = []
        bm25_scores_by_id: dict[str, float] = {}
        if _bm25_index and _bm25_unit_ids and query_tokens:
            bm25_scores = _bm25_index.get_scores(query_tokens)
            ranked_pairs = sorted(
                zip(_bm25_unit_ids, bm25_scores), key=lambda x: x[1], reverse=True
            )[:n_results * 8]
            bm25_ranked = [uid for uid, sc in ranked_pairs if sc > 0]
            bm25_scores_by_id = {uid: float(sc) for uid, sc in ranked_pairs if sc > 0}

        # ── Signal 3: lexical BM25 over raw chunks ──────────────────────────
        chunk_bm25_ranked: list[str] = []
        chunk_bm25_scores_by_id: dict[str, float] = {}
        if _chunk_bm25_index and _chunk_ids and query_tokens:
            chunk_scores = _chunk_bm25_index.get_scores(query_tokens)
            ranked_pairs = sorted(
                zip(_chunk_ids, chunk_scores), key=lambda x: x[1], reverse=True
            )[:n_results * 6]
            chunk_bm25_ranked = [cid for cid, sc in ranked_pairs if sc > 0]
            chunk_bm25_scores_by_id = {cid: float(sc) for cid, sc in ranked_pairs if sc > 0}

        # ── Signal 4: direct entity/subject lookup ──────────────────────────
        entity_ranked: list[str] = []
        entity_scores: dict[str, float] = {}
        q_token_set = set(query_tokens)
        if _entity_index and q_token_set:
            normalized_query = " ".join(query_tokens)
            for entity_name, uid_set in _entity_index.items():
                ent_tokens = set(_tokenize_search(entity_name))
                if not ent_tokens:
                    continue
                phrase_hit = entity_name in normalized_query
                overlap = len(ent_tokens & q_token_set)
                if phrase_hit or overlap:
                    weight = 4.0 if phrase_hit else float(overlap)
                    for uid in uid_set:
                        entity_scores[uid] = entity_scores.get(uid, 0.0) + weight
            entity_ranked = sorted(entity_scores, key=lambda uid: entity_scores[uid], reverse=True)[:n_results * 6]

        # ── Signal 5: one-hop knowledge graph expansion ─────────────────────
        seed_ids = _rrf_fuse([vector_unit_ranked, bm25_ranked, entity_ranked])[:max(n_results * 2, 10)]
        seed_entities: set[str] = set()
        for uid in seed_ids:
            unit = unit_by_id.get(uid)
            if not unit:
                continue
            if unit.get("subject"):
                seed_entities.add(unit["subject"].lower())
            seed_entities.update(ent.lower() for ent in unit.get("entities", []))

        graph_ranked: list[str] = []
        graph_relationships: list[dict] = []
        if seed_entities:
            for rel in brain.get("relationships", []):
                frm = rel.get("from", "").lower()
                to = rel.get("to", "").lower()
                if frm in seed_entities or to in seed_entities:
                    graph_relationships.append(rel)
                    rel_uid = rel.get("unitId")
                    if rel_uid in unit_by_id and rel_uid not in graph_ranked:
                        graph_ranked.append(rel_uid)
                    other = to if frm in seed_entities else frm
                    for unit in searchable_units:
                        subject = unit.get("subject", "").lower()
                        entities = {ent.lower() for ent in unit.get("entities", [])}
                        if other and (subject == other or other in entities):
                            uid = unit["id"]
                            if uid not in graph_ranked:
                                graph_ranked.append(uid)
                            break

        # ── Fuse and rerank unit candidates with temporal/confidence signals ─
        source_lists = [
            (vector_unit_ranked, 2.0),
            (bm25_ranked, 1.6),
            (entity_ranked, 1.35),
            (graph_ranked, 1.0),
        ]
        fused_scores: dict[str, float] = {}
        for ranked, weight in source_lists:
            for rank, uid in enumerate(ranked):
                fused_scores[uid] = fused_scores.get(uid, 0.0) + weight / (60 + rank + 1)

        scored_ids = []
        for uid, base_score in fused_scores.items():
            unit = unit_by_id.get(uid)
            if not unit:
                continue
            confidence = float(unit.get("confidence", 0.7))
            temporal_boost = _unit_temporal_score(unit, temporal_intent)
            stale_penalty = 0.55 if unit.get("stale") or unit.get("supersededBy") else 1.0
            final_score = base_score * (0.65 + confidence) * temporal_boost * stale_penalty
            scored_ids.append((uid, final_score))
        fused_ids = [uid for uid, _ in sorted(scored_ids, key=lambda item: item[1], reverse=True)[:n_results]]

        for uid in fused_ids:
            unit = unit_by_id.get(uid)
            if not unit:
                continue
            retrieved_ids.append(uid)
            retrieved_docs.append(unit.get("statement", ""))
            retrieved_metas.append({
                "kind": unit.get("kind", "fact"),
                "confidence": float(unit.get("confidence", 0.7)),
                "subject": unit.get("subject", ""),
                "sector": unit.get("sector", "General"),
                "department": unit.get("department", "general"),
                "entities": unit.get("entities", []),
                "disputed": unit.get("disputed", False),
                "stale": unit.get("stale", False),
                "supersededBy": unit.get("supersededBy"),
                "validFrom": unit.get("validFrom"),
                "validTo": unit.get("validTo"),
                "effectiveDate": unit.get("effectiveDate"),
                "temporalStatus": unit.get("temporalStatus", "unknown"),
            })

        # ── Fuse raw chunk candidates for source-excerpt fallback ────────────
        chunk_scores: dict[str, float] = {}
        for ranked, weight in ((vector_chunk_ranked, 1.6), (chunk_bm25_ranked, 1.9)):
            for rank, cid in enumerate(ranked):
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + weight / (60 + rank + 1)
        fused_chunk_ids = [
            cid for cid, _ in sorted(chunk_scores.items(), key=lambda item: item[1], reverse=True)
            if cid in chunk_by_id
        ][:3]
        for cid in fused_chunk_ids:
            chunk = chunk_by_id.get(cid)
            if not chunk:
                continue
            retrieved_chunk_ids.append(cid)
            retrieved_chunks.append(chunk)

        seen_rels: set[str] = set()
        for rel in graph_relationships[: max(3, n_results)]:
            rel_id = rel.get("id") or f"{rel.get('from')}:{rel.get('relation')}:{rel.get('to')}"
            if rel_id in seen_rels:
                continue
            seen_rels.add(rel_id)
            relationship_context.append(
                f"{rel.get('from', '')} {rel.get('relation', '')} {rel.get('to', '')}"
            )

        debug.update({
            "vector_unit_hits": _rank_debug(vector_unit_ranked, vector_unit_scores),
            "vector_chunk_hits": _rank_debug(vector_chunk_ranked, vector_chunk_scores),
            "bm25_hits": _rank_debug(bm25_ranked, bm25_scores_by_id),
            "chunk_bm25_hits": _rank_debug(chunk_bm25_ranked, chunk_bm25_scores_by_id),
            "entity_hits": _rank_debug(entity_ranked, entity_scores),
            "graph_hits": _rank_debug(graph_ranked),
            "final_unit_ids": retrieved_ids,
            "final_chunk_ids": retrieved_chunk_ids,
        })

        _debug_event(
            "retrieve.hybrid",
            "Hybrid BM25 + vector + graph retrieval complete",
            query=query,
            temporal_mode=temporal_intent.get("mode"),
            target_date=temporal_intent.get("target_date"),
            searchable_units=len(searchable_units),
            raw_chunks=len(raw_chunks),
            vector_unit_hits=len(vector_unit_ranked),
            vector_chunk_hits=len(vector_chunk_ranked),
            bm25_hits=len(bm25_ranked),
            chunk_bm25_hits=len(chunk_bm25_ranked),
            entity_hits=len(entity_ranked),
            graph_hits=len(graph_ranked),
            relationships=len(relationship_context),
            final_unit_ids=",".join(retrieved_ids),
            final_chunk_ids=",".join(retrieved_chunk_ids),
        )

        if retrieved_docs or retrieved_chunks:
            context_lines = []
            disputed_facts = []
            if retrieved_docs:
                context_lines.append("Facts:")
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
                temporal_bits = []
                if m.get("temporalStatus"):
                    temporal_bits.append(f"status:{m.get('temporalStatus')}")
                if m.get("effectiveDate"):
                    temporal_bits.append(f"effective:{m.get('effectiveDate')}")
                if m.get("validFrom"):
                    temporal_bits.append(f"valid_from:{m.get('validFrom')}")
                if m.get("validTo"):
                    temporal_bits.append(f"valid_to:{m.get('validTo')}")
                temporal_str = f" [{', '.join(temporal_bits)}]" if temporal_bits else ""
                context_lines.append(f"F{i}.{tag_str}{dept_str}{temporal_str} {doc}")
            if relationship_context:
                context_lines.append("\nGraph relationships:")
                for i, rel_text in enumerate(relationship_context, 1):
                    context_lines.append(f"R{i}. {rel_text}")
            if retrieved_chunks:
                context_lines.append("\nRaw source excerpts:")
                for i, chunk in enumerate(retrieved_chunks, 1):
                    source_title = chunk.get("sourceTitle") or chunk.get("sourceId", "source")
                    text = chunk.get("text", "")
                    if len(text) > 1800:
                        text = text[:1800] + "..."
                    context_lines.append(
                        f"C{i}. [{source_title} chunk {chunk.get('chunkIndex')}] {text}"
                    )
            context_section = "\n".join(context_lines)

            disputed_note = ""
            if disputed_facts:
                disputed_note = (
                    f"\nFacts {disputed_facts} are DISPUTED — multiple sources contradict. "
                    f"If your answer relies on them, explicitly call out the conflict.\n"
                )

            user_prompt = (
                f"Retrieved company knowledge:\n"
                f"{context_section}\n{disputed_note}\n"
                f"Question: {query}\n"
                f"Answer:"
            )
            system_msg = (
                "You are a company knowledge assistant. Rules:\n"
                "1. Use ONLY the Facts, Graph relationships, and Raw source excerpts above. Never invent names, services, or numbers.\n"
                "2. Facts are the primary source. Raw source excerpts are fallback evidence when extracted facts are missing or incomplete.\n"
                "3. If you rely on a raw source excerpt because no fact covers the answer, say the answer is based on source excerpt context.\n"
                "4. Cite every concrete claim inline with the evidence ID that supports it, using F1, R1, or C1 labels.\n"
                "5. Do not turn implications into facts. If a causal link is not explicitly stated, say the retrieved evidence does not explicitly state it.\n"
                "6. For WHY/root-cause/incident questions, only name causes that the context directly states as causes. Do not add deployment, infra, or process assumptions.\n"
                "7. Always name the specific person, team, or system only when the context names them. Never say 'the company' or 'someone'.\n"
                "8. Prefer fresh facts; ignore facts marked SUPERSEDED unless the user explicitly asks about historical state.\n"
                "9. For time-sensitive questions, use status/effective/valid_from/valid_to metadata. "
                "For 'now/current' questions, prefer current or unknown facts over future/historical facts. "
                "For future or historical questions, use the facts matching that date.\n"
                "10. If facts are marked DISPUTED, say so plainly: \"The sources disagree — A says X, B says Y.\"\n"
                "11. If the retrieved context does not answer the question, reply exactly: 'The brain does not have this information yet.'\n"
                "12. Be brief. One to three sentences unless the user asks for detail."
            )
        else:
            user_prompt = f"Question: {query}"
            system_msg = (
                "The company brain has no relevant retrieved knowledge. "
                "Reply exactly: 'The brain does not have this information yet.'"
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
                        "Never invent facts. Never add software-engineering explanations that are not explicitly supported.\n\n"
                        "Format your response as:\n"
                        "1. A direct answer in 1-3 sentences with inline citations like [F1], [C2], or [R1].\n"
                        "2. A 'Sources:' bullet list citing each evidence item you used.\n"
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
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_docs": (
                retrieved_docs
                + [f"[graph] {rel}" for rel in relationship_context]
                + [
                    f"[raw chunk:{chunk.get('id')}] {chunk.get('text', '')[:1000]}"
                    for chunk in retrieved_chunks
                ]
            ),
            "latency_ms": latency_ms,
            "retrieval_mode": "hybrid_bm25_vector_graph",
            "retrieval_debug": debug,
            "verification_context": (
                retrieved_docs
                + [f"[graph] {rel}" for rel in relationship_context]
                + [
                    f"[raw chunk:{chunk.get('id')}] {chunk.get('text', '')[:1000]}"
                    for chunk in retrieved_chunks
                ]
            ),
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
            "You are the BrainOS grounding judge. Your job is to audit whether an "
            "answer is supported by the retrieved company context. Be strict about "
            "unsupported claims, but do not punish an answer for being concise.\n\n"
            "CONTEXT TYPES:\n"
            "- Normal numbered items are extracted knowledge units or graph context.\n"
            "- Items beginning with [raw chunk:...] are raw source excerpts. They are valid evidence, "
            "but weaker than extracted knowledge units.\n\n"
            f"RETRIEVED CONTEXT:\n{ctx}\n\n"
            f"QUESTION:\n{query}\n\n"
            f"ANSWER:\n{answer}\n\n"
            "EVALUATION RULES:\n"
            "1. Every concrete answer claim must be supported by at least one context item.\n"
            "2. Names, services, dates, numbers, policies, owners, time windows, APIs, and tools "
            "must appear in or be directly implied by context.\n"
            "3. If the answer says the brain lacks information, that is grounded only when the "
            "retrieved context does not answer the question.\n"
            "4. If the answer relies only on raw chunks, it may still be grounded, but set "
            "raw_chunk_only=true and cap confidence at 0.82 unless the excerpt states it directly.\n"
            "5. If the answer contradicts any retrieved fact, set grounded=false and confidence <= 0.2.\n"
            "6. If the answer is correct but misses part of a multi-part question, set partial=true.\n"
            "7. Do not require exact wording. Reasonable paraphrases are allowed when the same "
            "entities and facts are present.\n\n"
            "SCORE GUIDE:\n"
            "- 1.00: all claims directly supported by extracted facts/graph context.\n"
            "- 0.85: all claims supported, with minor paraphrase or raw chunk support.\n"
            "- 0.65: mostly supported but incomplete or lightly inferred.\n"
            "- 0.40: weak support; important claim missing.\n"
            "- 0.20: fabricated or contradicted claim.\n"
            "- 0.00: unrelated to context or directly contradicts context.\n\n"
            "Return JSON only. No markdown. No prose outside JSON. Use this exact shape:\n"
            "{"
            '"confidence": 0.0, '
            '"grounded": true, '
            '"partial": false, '
            '"raw_chunk_only": false, '
            '"supporting_context_ids": ["1"], '
            '"unsupported_claims": [], '
            '"missing_aspects": [], '
            '"contradictions": [], '
            '"feedback": "one short sentence"'
            "}"
        )
        client, model = _resolve_override("feedback", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=320,
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
            try:
                feedback_confidence = float(parsed.get("confidence", 1.0) or 0.0)
            except (TypeError, ValueError):
                feedback_confidence = 0.0
            if feedback_confidence == 0.0:
                _debug_event(
                    "feedback.zero_confidence",
                    "Feedback model returned zero confidence",
                    query=query,
                    raw=raw,
                    feedback=parsed.get("feedback"),
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
    title: Optional[str] = None
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
    request_t0 = time.time()
    title = req.title or (req.content.strip().splitlines()[0][:80] if req.content.strip() else f"Untitled {req.kind}")
    _debug_event(
        "ingest.text.start",
        "Received text ingestion request",
        title=title,
        kind=req.kind,
        url=req.url,
        model=req.model,
        chars=len(req.content),
    )
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    _debug_event(
        "ingest.text.source",
        "Created source record",
        source_id=source_id,
    )

    extraction = ingest_agent.extract_from_text(
        req.kind, title, req.content, model_override=req.model,
    )

    source = {
        "id": source_id,
        "kind": req.kind,
        "title": title,
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
        raw_chunks=_chunk_text(req.content, max_chars=_MAX_EXTRACTION_CHARS),
    )
    _debug_event(
        "ingest.text.done",
        "Text ingestion complete",
        source_id=source_id,
        elapsed_ms=int((time.time() - request_t0) * 1000),
        units_extracted=len(extraction.get("units", [])),
        entities_extracted=len(extraction.get("entities", [])),
        relationships_extracted=len(extraction.get("relationships", [])),
        units_stored=result.get("units_stored"),
        entities_stored=result.get("entities_stored"),
        relationships_stored=result.get("relationships_stored"),
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


def _extract_docx_text(data: bytes) -> str:
    """Extract paragraphs and table text from a .docx file using the zipped Word XML."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as docx:
            xml_parts = [
                name for name in docx.namelist()
                if name == "word/document.xml" or name.startswith("word/header") or name.startswith("word/footer")
            ]
            paragraphs: list[str] = []
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            for part in xml_parts:
                root = ET.fromstring(docx.read(part))
                for para in root.findall(".//w:p", ns):
                    texts = [node.text or "" for node in para.findall(".//w:t", ns)]
                    line = "".join(texts).strip()
                    if line:
                        paragraphs.append(line)
            return "\n\n".join(paragraphs)
    except Exception as e:
        return f"[DOCX extraction failed: {e}]"


def _extract_doc_text(filename: str, data: bytes) -> str:
    """
    Best-effort legacy .doc extraction. On macOS, textutil can convert old Word
    documents to text. If unavailable, ask the user to save as .docx.
    """
    textutil = shutil.which("textutil")
    if not textutil:
        return "[DOC extraction failed: legacy .doc requires macOS textutil. Save the file as .docx and upload again.]"

    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, filename or "upload.doc")
        out = os.path.join(tmpdir, "upload.txt")
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run(
                [textutil, "-convert", "txt", "-output", out, src],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            with open(out, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            return f"[DOC extraction failed: {e}]"

def _extract_file_text(filename: str, data: bytes) -> str:
    """Extract plain text from PDF, Word, TXT, MD, or CSV uploads."""
    name = filename.lower()
    _debug_event(
        "file.extract.start",
        "Extracting text from uploaded file",
        filename=filename,
        bytes=len(data),
    )
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            _debug_event(
                "file.extract.pdf",
                "PDF text extraction complete",
                filename=filename,
                pages=len(reader.pages),
                chars=len(text),
            )
            if not text.strip():
                return "[PDF has no selectable text — it may be a scanned/image-based PDF. Try the Image tab instead.]"
            return text
        except Exception as e:
            _debug_event(
                "file.extract.error",
                "PDF text extraction failed",
                filename=filename,
                error=e,
            )
            return f"[PDF extraction failed: {e}]"
    if name.endswith(".docx"):
        text = _extract_docx_text(data)
        _debug_event(
            "file.extract.docx",
            "DOCX text extraction complete",
            filename=filename,
            chars=len(text),
        )
        return text
    if name.endswith(".doc"):
        text = _extract_doc_text(filename, data)
        _debug_event(
            "file.extract.doc",
            "DOC text extraction complete",
            filename=filename,
            chars=len(text),
        )
        return text
    # TXT / MD / CSV — decode directly
    for enc in ("utf-8", "latin-1"):
        try:
            text = data.decode(enc)
            _debug_event(
                "file.extract.text",
                "Plain text decode complete",
                filename=filename,
                encoding=enc,
                chars=len(text),
            )
            return text
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    _debug_event(
        "file.extract.text",
        "Plain text decode complete with replacement characters",
        filename=filename,
        encoding="utf-8-replace",
        chars=len(text),
    )
    return text




@app.post("/api/ingest_file")
async def ingest_file(
    title: Optional[str] = Form(None),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """
    File upload pipeline:
      PDF/DOC/DOCX/TXT/MD/CSV → text extraction → 70B extraction → ChromaDB → brain.json
    """
    request_t0 = time.time()
    data = await file.read()
    filename = file.filename or "upload"
    if not title:
        title = filename.rsplit(".", 1)[0] or filename
    _debug_event(
        "ingest.file.start",
        "Received file ingestion request",
        title=title,
        kind=kind,
        url=url,
        model=model,
        filename=file.filename,
        content_type=file.content_type,
    )
    _debug_event(
        "ingest.file.read",
        "Uploaded file bytes read",
        filename=filename,
        bytes=len(data),
    )
    text = _extract_file_text(filename, data)

    if (
        not text.strip()
        or text.startswith("[PDF has no selectable")
        or text.startswith("[PDF extraction failed")
        or text.startswith("[DOC extraction failed")
        or text.startswith("[DOCX extraction failed")
    ):
        _debug_event(
            "ingest.file.reject",
            "File did not produce ingestible text",
            filename=filename,
            detail=text,
        )
        raise HTTPException(status_code=422, detail=text if text.startswith("[") else "Could not extract any text from the file.")

    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    _debug_event(
        "ingest.file.source",
        "Created source record",
        source_id=source_id,
        filename=filename,
        chars=len(text),
    )

    # Chunk large documents so each LLM call fits inside the context window,
    # then merge all extracted units + entities across chunks.
    chunks = _chunk_text(text, max_chars=_MAX_EXTRACTION_CHARS)
    _debug_event(
        "ingest.file.chunks",
        "Top-level file chunking complete",
        source_id=source_id,
        chunks=len(chunks),
        max_chars=_MAX_EXTRACTION_CHARS,
        chunk_chars=",".join(str(len(chunk)) for chunk in chunks),
    )
    all_units: list[dict] = []
    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    for idx, chunk in enumerate(chunks, start=1):
        _debug_event(
            "ingest.file.chunk.start",
            "Processing file chunk",
            source_id=source_id,
            chunk=idx,
            total_chunks=len(chunks),
            chars=len(chunk),
        )
        extraction = ingest_agent.extract_from_text(
            source_type=kind,
            title=title,
            content=chunk,
            model_override=model,
        )
        chunk_units = extraction.get("units", [])
        chunk_entities = extraction.get("entities", [])
        chunk_relationships = extraction.get("relationships", [])
        _debug_event(
            "ingest.file.chunk.done",
            "File chunk extraction complete",
            source_id=source_id,
            chunk=idx,
            units=len(chunk_units),
            entities=len(chunk_entities),
            relationships=len(chunk_relationships),
        )
        all_units.extend(chunk_units)
        all_entities.extend(chunk_entities)
        all_relationships.extend(chunk_relationships)

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
        relationships=all_relationships,
        raw_chunks=chunks,
    )
    _debug_event(
        "ingest.file.done",
        "File ingestion complete",
        source_id=source_id,
        filename=filename,
        elapsed_ms=int((time.time() - request_t0) * 1000),
        units_extracted=len(all_units),
        entities_extracted=len(all_entities),
        relationships_extracted=len(all_relationships),
        units_stored=result.get("units_stored"),
        entities_stored=result.get("entities_stored"),
        relationships_stored=result.get("relationships_stored"),
    )

    return {
        "message": f"File '{filename}' ingested ({len(chunks)} chunk(s)).",
        "chars_extracted": len(text),
        "chunks_processed": len(chunks),
        "source_id": source_id,
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "relationships_extracted": len(all_relationships),
        **result,
    }


@app.post("/api/ingest_image")
async def ingest_image(
    title: Optional[str] = Form(None),
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
    request_t0 = time.time()
    image_data = await file.read()
    mime = file.content_type or "image/png"
    if not title:
        fname = file.filename or "image"
        title = fname.rsplit(".", 1)[0] or fname
    _debug_event(
        "ingest.image.start",
        "Received image ingestion request",
        title=title,
        kind=kind,
        url=url,
        vlm_model=model,
        text_model=text_model,
        filename=file.filename,
        content_type=file.content_type,
    )
    _debug_event(
        "ingest.image.read",
        "Uploaded image bytes read",
        filename=file.filename,
        mime=mime,
        bytes=len(image_data),
    )

    # Step 1: VLM converts image to text
    description = ingest_agent.describe_image(image_data, mime, model_override=model)
    _debug_event(
        "ingest.image.description",
        "Image description ready for text extraction",
        chars=len(description or ""),
        preview=description or "",
    )

    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    _debug_event(
        "ingest.image.source",
        "Created source record",
        source_id=source_id,
        filename=file.filename,
    )

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
        raw_chunks=[description],
    )
    _debug_event(
        "ingest.image.done",
        "Image ingestion complete",
        source_id=source_id,
        elapsed_ms=int((time.time() - request_t0) * 1000),
        description_chars=len(description or ""),
        units_extracted=len(extraction.get("units", [])),
        entities_extracted=len(extraction.get("entities", [])),
        relationships_extracted=len(extraction.get("relationships", [])),
        units_stored=result.get("units_stored"),
        entities_stored=result.get("entities_stored"),
        relationships_stored=result.get("relationships_stored"),
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
            "capturedAt": item.get("timestamp", _utc_now_iso()),
        }
        result = struct_agent.embed_and_store(
            source_id=source_id,
            source=source,
            units=extraction.get("units", []),
            entities=extraction.get("entities", []),
            relationships=extraction.get("relationships", []),
            raw_chunks=_chunk_text(item.get("content", ""), max_chars=_MAX_EXTRACTION_CHARS),
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

    try:
        exec_result = exec_agent.execute(req.query, model_override=req.model)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")

    verification_context = exec_result.get("verification_context") or exec_result["retrieved_docs"]
    answer_revised = False
    draft_answer = exec_result["answer"]
    try:
        feedback = feedback_agent.evaluate(
            query=req.query,
            answer=draft_answer,
            context_docs=verification_context,
            model_override=req.model,
        )
    except Exception:
        feedback = {"confidence": 0.0, "grounded": False, "feedback": "Evaluation unavailable."}

    try:
        confidence = float(feedback.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    unsupported = feedback.get("unsupported_claims") or []
    contradictions = feedback.get("contradictions") or []
    needs_revision = (
        feedback.get("grounded") is False
        or confidence < 0.72
        or bool(unsupported)
        or bool(contradictions)
    )

    if needs_revision and verification_context:
        _debug_event(
            "answer.revise.start",
            "Verifier requested evidence-constrained answer revision",
            confidence=confidence,
            grounded=feedback.get("grounded"),
            unsupported=len(unsupported),
            contradictions=len(contradictions),
        )
        revised_answer = exec_agent.revise_answer(
            query=req.query,
            draft_answer=draft_answer,
            context_docs=verification_context,
            verification=feedback,
            model_override=req.model,
        )
        if revised_answer and revised_answer != draft_answer:
            exec_result["answer"] = revised_answer
            answer_revised = True
            try:
                revised_feedback = feedback_agent.evaluate(
                    query=req.query,
                    answer=revised_answer,
                    context_docs=verification_context,
                    model_override=req.model,
                )
                revised_feedback["pre_revision_feedback"] = feedback
                feedback = revised_feedback
            except Exception:
                feedback["revision_note"] = "Answer was revised, but second-pass evaluation failed."

    return {
        "query": req.query,
        "answer": exec_result["answer"],
        "draft_answer": draft_answer if answer_revised else None,
        "answer_revised": answer_revised,
        "used": exec_result["retrieved_ids"],
        "retrieved_texts": exec_result["retrieved_docs"],  # actual sentences sent to the model
        "latency_ms": exec_result["latency_ms"],
        "retrieval_mode": exec_result.get("retrieval_mode"),
        "retrieval_debug": exec_result.get("retrieval_debug"),
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


from integrations.slack_routes import create_slack_router

app.include_router(create_slack_router(
    ingest_agent=ingest_agent,
    struct_agent=struct_agent,
    exec_agent=exec_agent,
    feedback_agent=feedback_agent,
    chunk_text=_chunk_text,
    max_extraction_chars=_MAX_EXTRACTION_CHARS,
    utc_now_iso=_utc_now_iso,
    debug_event=_debug_event,
    is_sensitive=_is_sensitive,
))


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
