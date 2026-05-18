from __future__ import annotations
import json
import os
os.environ.setdefault("TQDM_DISABLE", "1")  # suppress sentence-transformers progress bar
import base64
import uuid
import time
import threading
import datetime
import queue as _stdlib_queue
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
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
        # Pass OPENAI_API_KEY when present so this client also works against
        # OpenAI's API (and any OpenAI-compatible endpoint that requires a
        # bearer token). Self-hosted vLLM servers ignore the header.
        headers: dict[str, str] = {}
        _key = os.getenv("OPENAI_API_KEY", "").strip()
        if _key:
            headers["Authorization"] = f"Bearer {_key}"
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers or None,
        )
        self.chat = _Chat(self._http)
        self.embeddings = _Embeddings(self._http)
        self.models = _Models(self._http)


# ── Claude API fallback client (used when vLLM endpoints are absent/unreachable) ─
# Uses httpx directly against Anthropic's Messages API, translating to/from
# OpenAI-compatible SimpleNamespace responses so the rest of the code is unchanged.

def _openai_messages_to_anthropic(messages: list) -> tuple[str | None, list]:
    """Split system prompt out and convert image_url blocks to Anthropic format."""
    system = None
    converted = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            system = m.get("content", "")
            continue
        content = m.get("content")
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
        elif isinstance(content, list):
            blocks = []
            for block in content:
                if block.get("type") == "text":
                    blocks.append({"type": "text", "text": block["text"]})
                elif block.get("type") == "image_url":
                    url = block["image_url"]["url"]
                    if url.startswith("data:"):
                        header, b64data = url.split(",", 1)
                        media_type = header.split(";")[0].split(":")[1]
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64data},
                        })
                    else:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "url", "url": url},
                        })
            converted.append({"role": role, "content": blocks})
        else:
            converted.append({"role": role, "content": str(content)})
    return system, converted


class _ClaudeChatCompletions:
    def __init__(self, http: httpx.Client):
        self._http = http

    def create(self, *, model, messages, max_tokens=None, temperature=None, **kwargs):
        system, converted = _openai_messages_to_anthropic(messages)
        payload: dict = {"model": model, "messages": converted, "max_tokens": max_tokens or 4096}
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature
        r = self._http.post("/messages", json=payload)
        r.raise_for_status()
        data = r.json()
        # Translate Anthropic response → OpenAI-style SimpleNamespace
        text = data["content"][0]["text"] if data.get("content") else ""
        usage = data.get("usage", {})
        return _to_obj({
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            },
            "model": model,
        })


class _ClaudeChat:
    def __init__(self, http: httpx.Client):
        self.completions = _ClaudeChatCompletions(http)


class _ClaudeModels:
    def __init__(self, model: str):
        self._model = model

    def list(self):
        return _to_obj({"data": [{"id": self._model}]})


class ClaudeAPIClient:
    """Drop-in replacement for VLLMClient backed by Anthropic Messages API via httpx."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        http = httpx.Client(
            base_url="https://api.anthropic.com/v1",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=600.0,
        )
        self.base_url = "https://api.anthropic.com/v1"
        self._model = model
        self.chat = _ClaudeChat(http)
        self.models = _ClaudeModels(model)
        self.embeddings = None  # Anthropic has no embeddings; sentence-transformers handles this


def _probe_endpoint(url: str, timeout: float = 5.0) -> bool:
    """Return True if the endpoint responds to GET /models within timeout."""
    try:
        r = httpx.get(f"{url.rstrip('/')}/models", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


# ── LLM provider selection ────────────────────────────────────────────────────
# BrainOS supports two providers, controlled by LLM_PROVIDER:
#
#   LLM_PROVIDER=claude   →  Anthropic Claude API (requires CLAUDE_API_KEY)
#   LLM_PROVIDER=custom   →  any OpenAI-compatible endpoint, e.g. self-hosted
#                            vLLM on a GPU. Requires LLM_API_BASE (or its legacy
#                            alias VLLM_API_BASE) and LLM_MODEL_NAME.
#
# If LLM_PROVIDER is unset, we auto-detect: prefer a reachable custom endpoint,
# otherwise fall back to Claude if a key is present.
_provider_env = os.getenv("LLM_PROVIDER", "").strip().lower()

# Custom-endpoint env vars (LLM_* is the canonical name; VLLM_*/VLM_* are kept
# as backwards-compatible aliases).
_raw_llm_url = (os.getenv("LLM_API_BASE") or os.getenv("VLLM_API_BASE") or "").strip()
_raw_vlm_url = (os.getenv("VLM_API_BASE") or "").strip()

# Claude env vars.
_claude_key   = os.getenv("CLAUDE_API_KEY", "").strip()
_claude_model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

_USING_CLAUDE_FALLBACK = False

def _choose_provider() -> str:
    if _provider_env in ("claude", "custom"):
        return _provider_env
    # Auto-detect: prefer a reachable custom endpoint, else Claude.
    if _raw_llm_url and _probe_endpoint(_raw_llm_url):
        return "custom"
    if _claude_key:
        return "claude"
    return "custom"  # last resort — server starts but calls will fail

_provider = _choose_provider()

if _provider == "custom":
    if not _raw_llm_url:
        print("[BrainOS] WARNING: LLM_PROVIDER=custom but LLM_API_BASE is empty — ingestion/ask will fail")
    vllm_url = _raw_llm_url or "http://localhost:8000/v1"
    vlm_url  = _raw_vlm_url or vllm_url
    llm_client = VLLMClient(base_url=vllm_url)
    vlm_client = VLLMClient(base_url=vlm_url)
    print(f"[BrainOS] Provider: custom endpoint ({vllm_url})")
elif _provider == "claude":
    if not _claude_key:
        print("[BrainOS] WARNING: LLM_PROVIDER=claude but CLAUDE_API_KEY is empty — ingestion/ask will fail")
    _USING_CLAUDE_FALLBACK = True
    vllm_url = "https://api.anthropic.com/v1"
    vlm_url  = vllm_url
    llm_client = ClaudeAPIClient(api_key=_claude_key or "missing", model=_claude_model)
    vlm_client = ClaudeAPIClient(api_key=_claude_key or "missing", model=_claude_model)
    print(f"[BrainOS] Provider: Claude API ({_claude_model})")


def _resolve_model(client, env_name: str, env_value: str) -> str:
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


# Defaults are provider-aware: with provider=claude, MODEL_NAME defaults to
# CLAUDE_MODEL so users only have to set one env var. With provider=custom,
# MODEL_NAME must match a model served at LLM_API_BASE.
if _USING_CLAUDE_FALLBACK:
    _model_env = os.getenv("MODEL_NAME", _claude_model)
    _vlm_model_env = os.getenv("VLM_MODEL_NAME", _claude_model)
else:
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
        self._client_cache: dict[str, object] = {
            vllm_url: llm_client,
            vlm_url: vlm_client,
        }
        self._routes: dict[str, tuple] = {}
        for task in TASKS:
            self._routes[task] = self._resolve(task)

    def _resolve(self, task: str) -> tuple:
        tu = task.upper()
        # VLM has historic env var names
        if task == "vlm":
            return vlm_client, VLM_MODEL_NAME
        # In Claude fallback mode, ignore per-task API_BASE overrides
        if _USING_CLAUDE_FALLBACK:
            return llm_client, MODEL_NAME
        api_base = os.getenv(f"{tu}_API_BASE", "").strip() or vllm_url
        model = os.getenv(f"{tu}_MODEL", "").strip() or MODEL_NAME
        if api_base not in self._client_cache:
            self._client_cache[api_base] = VLLMClient(base_url=api_base)
        return self._client_cache[api_base], model

    def get(self, task: str) -> tuple:
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
# BRAIN_DATA_DIR env var lets Docker/Railway point to a persistent volume.
_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DATA_DIR = os.environ.get("BRAIN_DATA_DIR") or os.path.join(_project_root, "data")
CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
BRAIN_JSON = os.path.join(DATA_DIR, "brain.json")
DECISION_ALERTS_JSON = os.path.join(DATA_DIR, "decision_alerts.json")
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
    # Use ChromaDB's built-in ONNX embedding (all-MiniLM-L6-v2 via onnxruntime).
    # No torch dependency — keeps the Docker image lean for cloud deployment.
    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    EMBEDDING_BACKEND = f"CPU · ONNX · all-MiniLM-L6-v2 (chromadb default)"

print(f"[BrainOS] Embedding backend: {EMBEDDING_BACKEND}")

chroma_client = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False, allow_reset=True),
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


# ── CEO decision alerts ───────────────────────────────────────────────────────
# Realtime Slack ingestion writes normal BrainOS units first. This lightweight
# store keeps the separate "executive alert" surface durable without adding a DB.
def _decision_alert_min_confidence() -> float:
    raw = os.getenv("CEO_DECISION_ALERT_MIN_CONFIDENCE", "0.78")
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.78


class DecisionAlertStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._listeners: list[_stdlib_queue.Queue] = []

    def _read_unlocked(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []

    def _write_unlocked(self, alerts: list[dict]):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2)

    def list(self, *, include_closed: bool = False) -> list[dict]:
        with self._lock:
            alerts = self._read_unlocked()
        if include_closed:
            return alerts
        return [a for a in alerts if a.get("status") == "open"]

    def create_for_source(self, *, source: dict, units: list[dict]) -> list[dict]:
        min_conf = _decision_alert_min_confidence()
        now = _utc_now_iso()
        created: list[dict] = []
        with self._lock:
            alerts = self._read_unlocked()
            existing_unit_ids = {a.get("unitId") for a in alerts}
            for unit in units:
                if unit.get("id") in existing_unit_ids:
                    continue
                if unit.get("kind") != "decision":
                    continue
                if unit.get("stale") or unit.get("supersededBy"):
                    continue
                try:
                    confidence = float(unit.get("confidence", 0.0) or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < min_conf:
                    continue

                evidence = next(
                    (ev for ev in unit.get("evidence", []) if isinstance(ev, dict)),
                    {},
                )
                alert = {
                    "id": str(uuid.uuid4())[:10],
                    "unitId": unit.get("id"),
                    "statement": unit.get("statement", ""),
                    "subject": unit.get("subject", ""),
                    "confidence": confidence,
                    "sourceId": source.get("id") or evidence.get("sourceId"),
                    "sourceTitle": source.get("title", ""),
                    "channelId": source.get("channelId"),
                    "channelName": source.get("channelName"),
                    "threadTs": source.get("threadTs"),
                    "evidenceQuote": evidence.get("quote", ""),
                    "createdAt": now,
                    "status": "open",
                }
                alerts.insert(0, alert)
                created.append(alert)
            if created:
                self._write_unlocked(alerts)

        for alert in created:
            self._notify("decision_alert.created", alert)
        return created

    def update_status(self, alert_id: str, status: str) -> dict | None:
        now = _utc_now_iso()
        updated = None
        with self._lock:
            alerts = self._read_unlocked()
            for alert in alerts:
                if alert.get("id") == alert_id:
                    alert["status"] = status
                    if status == "acknowledged":
                        alert["acknowledgedAt"] = now
                    elif status == "dismissed":
                        alert["dismissedAt"] = now
                    updated = alert
                    break
            if updated:
                self._write_unlocked(alerts)
        if updated:
            self._notify(f"decision_alert.{status}", updated)
        return updated

    def listen(self) -> _stdlib_queue.Queue:
        q: _stdlib_queue.Queue = _stdlib_queue.Queue(maxsize=256)
        with self._lock:
            self._listeners.append(q)
        return q

    def unlisten(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _notify(self, event: str, alert: dict):
        payload = {"event": event, "alert": alert}
        with self._lock:
            dead = []
            for q in self._listeners:
                try:
                    q.put_nowait(payload)
                except _stdlib_queue.Full:
                    dead.append(q)
            for q in dead:
                self._listeners.remove(q)


decision_alerts = DecisionAlertStore(DECISION_ALERTS_JSON)

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


# ── Entity canonicalization ──────────────────────────────────────────────────
# Collapse variants like "Intel" / "Intel Corp" / "Intel Corporation" / "Intel,
# Inc." onto a single node. We strip corporate suffix tokens and punctuation,
# then compare on a normalized key. Aliases are also indexed so the model can
# emit `{name: "Intel Corporation", aliases: ["Intel"]}` and we'll merge.

_CORP_SUFFIX_TOKENS = {
    "inc", "incorporated", "corp", "corporation", "corporate",
    "ltd", "limited", "llc", "llp", "lp", "co", "company",
    "gmbh", "ag", "sa", "sas", "plc", "kg", "nv", "bv", "oy",
    "aps", "srl", "sl", "sarl", "kk", "pty",
    "holdings", "group", "holding", "industries",
}

_ARTICLE_TOKENS = {"the", "a", "an"}

_ENT_PUNCT_RE = re.compile(r"[.,;:'’\"!?()\[\]/&]+")


def _singularize(token: str) -> str:
    """Crude English plural → singular. Conservative on short tokens to avoid
    mangling proper nouns ('AMD' stays 'AMD'). Handles the common cases:
      companies → company   tomatoes → tomato   apples → apple
      boxes → box           processes → process  buses (kept as bus only via 's' rule below)
    Skips known non-plural endings: 'ss', 'is', 'us', 'os', 'as'.
    """
    if len(token) <= 3:
        return token
    # 'ies' → 'y'   (companies, policies, batteries)
    if token.endswith("ies") and token[-4] not in "aeiou":
        return token[:-3] + "y"
    # 'oes' → 'o'   (tomatoes, potatoes, heroes)
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    # '(s|x|z|sh|ch)es' → drop 'es'  (boxes, dishes, brushes, processes)
    if (token.endswith(("ses", "xes", "zes", "shes", "ches"))) and len(token) > 4:
        return token[:-2]
    # plain trailing 's', but skip false plurals
    if (token.endswith("s")
            and not token.endswith(("ss", "is", "us", "os", "as"))):
        return token[:-1]
    return token


def _canonical_entity_key(name: str) -> str:
    """Normalized comparison key. Steps applied in order:
      1. lowercase + strip punctuation
      2. drop leading articles  ("the AMD" / "an Onion" → "AMD" / "Onion")
      3. drop trailing corporate suffixes  ("Intel Corp" / "Intel, Inc." → "Intel")
      4. singularize each remaining token  ("tomatoes" → "tomato", "companies" → "company")
    So 'intel', 'Intel Corp', 'Intel, Inc.', 'The Intel Corporation' all
    canonicalize to 'intel'. Tomato / Tomatoes / tomato. AMD / The AMD. Etc.
    """
    if not name:
        return ""
    s = _ENT_PUNCT_RE.sub(" ", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split(" ")
    while len(parts) > 1 and parts[0] in _ARTICLE_TOKENS:
        parts.pop(0)
    while len(parts) > 1 and parts[-1] in _CORP_SUFFIX_TOKENS:
        parts.pop()
    parts = [_singularize(p) for p in parts]
    return " ".join(parts).strip()


def _entity_canonical_keys(entity: dict) -> set[str]:
    """All canonical keys identifying this entity (name + every alias)."""
    keys: set[str] = {_canonical_entity_key(entity.get("name", ""))}
    for a in entity.get("aliases", []) or []:
        keys.add(_canonical_entity_key(a))
    keys.discard("")
    return keys


def _pick_canonical_name(candidates: list[str]) -> str:
    """Pick the most canonical-looking display name from a list of variants.
    Heuristics:
      1. Prefer names that *have* a corporate suffix (more disambiguated).
      2. Then prefer the longest.
      3. Stable tiebreaker: first occurrence.
    """
    if not candidates:
        return ""
    def has_suffix(n: str) -> bool:
        last = n.lower().strip(".,").split()[-1] if n.strip() else ""
        return last in _CORP_SUFFIX_TOKENS
    ranked = sorted(
        enumerate(candidates),
        key=lambda iv: (not has_suffix(iv[1]), -len(iv[1]), iv[0]),
    )
    return ranked[0][1]


def _consolidate_entities(brain: dict) -> dict[str, str]:
    """Group `brain['entities']` by canonical key and merge duplicates in place.

    Returns a rename map {old_display_name: canonical_display_name} that the
    caller should apply to relationships and units so all references converge.
    Idempotent: a brain already free of duplicates returns {}.
    """
    entities = brain.get("entities", []) or []
    by_key: dict[str, list[dict]] = {}
    for ent in entities:
        for k in _entity_canonical_keys(ent):
            by_key.setdefault(k, []).append(ent)

    # Union-find: walk the key→entities map and group entities that share any key.
    seen_ids: set[int] = set()
    groups: list[list[dict]] = []
    for group_seed in by_key.values():
        unseen = [e for e in group_seed if id(e) not in seen_ids]
        if not unseen:
            continue
        group: list[dict] = []
        stack = list(unseen)
        while stack:
            ent = stack.pop()
            if id(ent) in seen_ids:
                continue
            seen_ids.add(id(ent))
            group.append(ent)
            for k in _entity_canonical_keys(ent):
                for sib in by_key.get(k, []):
                    if id(sib) not in seen_ids:
                        stack.append(sib)
        if group:
            groups.append(group)

    rename_map: dict[str, str] = {}
    survivors: list[dict] = []
    for group in groups:
        if len(group) == 1:
            survivors.append(group[0])
            continue
        # Merge group into one canonical entity
        names = [g["name"] for g in group if g.get("name")]
        canonical_name = _pick_canonical_name(names)
        winner = next(g for g in group if g["name"] == canonical_name)
        aliases: set[str] = set()
        for g in group:
            for a in g.get("aliases", []) or []:
                if a and a != canonical_name:
                    aliases.add(a)
            if g["name"] != canonical_name:
                aliases.add(g["name"])
                rename_map[g["name"]] = canonical_name
        winner["aliases"] = sorted(aliases)
        survivors.append(winner)

    # Preserve original ordering when nothing was merged, otherwise rebuild.
    if rename_map:
        # Keep relative order of first-occurrence of each surviving id
        order = {id(e): i for i, e in enumerate(entities)}
        survivors.sort(key=lambda e: order.get(id(e), 1 << 30))
        brain["entities"] = survivors
    return rename_map


def _apply_entity_renames(brain: dict, rename_map: dict[str, str]) -> None:
    """Rewrite stale entity names across relationships and units in place."""
    if not rename_map:
        return
    for rel in brain.get("relationships", []) or []:
        if rel.get("from") in rename_map:
            rel["from"] = rename_map[rel["from"]]
        if rel.get("to") in rename_map:
            rel["to"] = rename_map[rel["to"]]
    for u in brain.get("units", []) or []:
        if u.get("subject") in rename_map:
            u["subject"] = rename_map[u["subject"]]
        ents = u.get("entities") or []
        if ents:
            u["entities"] = sorted({rename_map.get(e, e) for e in ents if e})


def _build_entity_resolver(entities: list[dict]):
    """Return a callable that maps any name variant to the canonical display
    name. A 'variant' is any string whose canonical key matches the canonical
    key of an existing entity's name or aliases. Returns the input unchanged
    when no match is found, so unknown names pass through.

    Used at insert-time so freshly-extracted relationships and unit subjects/
    entities never reference a name that isn't in brain['entities']."""
    exact: dict[str, str] = {}       # lowercased name/alias → canonical display
    by_key: dict[str, str] = {}      # canonical key → canonical display
    for ent in entities or []:
        display = (ent.get("name") or "").strip()
        if not display:
            continue
        exact[display.lower()] = display
        key = _canonical_entity_key(display)
        if key:
            by_key.setdefault(key, display)
        for a in ent.get("aliases") or []:
            if not a:
                continue
            exact[a.lower()] = display
            ak = _canonical_entity_key(a)
            if ak:
                by_key.setdefault(ak, display)

    def resolve(name: str) -> str:
        if not name:
            return name
        hit = exact.get(name.lower())
        if hit:
            return hit
        key = _canonical_entity_key(name)
        if key and key in by_key:
            return by_key[key]
        return name

    return resolve


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
            # Preserve any pre-attached evidence entries (e.g. {"path": "..."}
            # set by the code-ingest handler so the /code page can locate ADR
            # units). Prepend the canonical sourceId/quote entry; filter out
            # any prior evidence that already pointed at this same source to
            # avoid double-counting.
            prior_evidence = [
                e for e in (u.get("evidence") or [])
                if isinstance(e, dict) and e.get("sourceId") != source_id
            ]
            pending.append((uid, {
                "id": uid,
                "kind": u.get("kind", "fact"),
                "department": dept,
                "subject": u.get("subject", ""),
                "statement": _normalize_statement(u),  # always self-contained
                "entities": u.get("entities", []),
                "sector": u.get("sector", "General"),
                "evidence": [{"sourceId": source_id, "quote": u.get("evidence_quote", "")}, *prior_evidence],
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

        # Entity dedup by canonical key (handles "Intel" / "Intel Corporation" /
        # "Intel Corp" / "Intel, Inc." → one node). Match against existing
        # names AND aliases via _canonical_entity_key; merge aliases on collision.
        new_entities = []
        for e in entities:
            raw_name = (e.get("name") or "").strip()
            if not raw_name:
                continue
            incoming_aliases = [a.strip() for a in (e.get("aliases") or []) if a and a.strip()]
            incoming_keys = {_canonical_entity_key(raw_name)}
            for a in incoming_aliases:
                incoming_keys.add(_canonical_entity_key(a))
            incoming_keys.discard("")

            existing = None
            for x in brain["entities"]:
                if incoming_keys & _entity_canonical_keys(x):
                    existing = x
                    break

            if existing:
                # Merge incoming name + aliases into the existing entity's
                # aliases, keeping the existing display name as canonical.
                aliases = set(existing.get("aliases") or [])
                if raw_name.lower() != (existing.get("name") or "").lower():
                    aliases.add(raw_name)
                for a in incoming_aliases:
                    if a.lower() != (existing.get("name") or "").lower():
                        aliases.add(a)
                existing["aliases"] = sorted(aliases)
            else:
                entity = {
                    "id": str(uuid.uuid4())[:8],
                    "name": raw_name,
                    "kind": e.get("kind", "concept"),
                    "aliases": incoming_aliases,
                }
                brain["entities"].insert(0, entity)
                new_entities.append(entity)

        # Resolve every incoming entity reference (relationship endpoints, unit
        # subjects, unit entity arrays) against the now-canonicalized entity
        # list. Prevents this-ingest's edges/units from pointing at a name
        # that's only an alias of an existing canonical entity — which would
        # otherwise spawn a phantom node on the graph view.
        resolve_entity = _build_entity_resolver(brain["entities"])
        for su in stored_units:
            if su.get("subject"):
                su["subject"] = resolve_entity(su["subject"])
            if su.get("entities"):
                su["entities"] = sorted({resolve_entity(e) for e in su["entities"] if e})

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

        # ── Step 6: consolidate entities (merge duplicates by canonical key,
        # e.g. "Intel" + "Intel Corporation") and rewrite relationships +
        # units to point at the canonical names. Idempotent.
        rename_map = _consolidate_entities(brain)
        if rename_map:
            _apply_entity_renames(brain, rename_map)
            _debug_event(
                "store.entities.consolidated",
                "Merged duplicate entities by canonical name",
                merges=rename_map,
            )

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

        # Code-map context — surfaces entity↔path links, symbol locations,
        # and module summaries when the question touches a code source. Cheap
        # (in-memory scan over the codebase blocks) and runs even when no
        # facts/chunks are retrieved, so a code-only question still gets help.
        code_context_lines = _code_context_for_query(query, brain)

        if retrieved_docs or retrieved_chunks or code_context_lines:
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
            if code_context_lines:
                context_lines.append("\nCode map:")
                for i, code_text in enumerate(code_context_lines, 1):
                    context_lines.append(f"K{i}. {code_text}")
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
                "1. Use ONLY the Facts, Graph relationships, Raw source excerpts, and Code map entries above. Never invent names, services, or numbers.\n"
                "2. Facts are the primary source. Raw source excerpts and Code map entries are fallback evidence when extracted facts are missing or incomplete.\n"
                "3. If you rely on a raw source excerpt or code-map entry because no fact covers the answer, say the answer is based on that source.\n"
                "4. Cite every concrete claim inline with the evidence ID that supports it, using F1, R1, C1, or K1 labels.\n"
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
                + code_context_lines
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
                + code_context_lines
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
# Async Job Queue
# ══════════════════════════════════════════════════════════════════════════════
# Single-worker FIFO queue for heavy LLM-bound work (text/file/image ingest).
# Routes enqueue jobs and return immediately with a job_id; one background
# thread processes them one at a time so concurrent uploads don't fight over
# the LLM endpoint. SSE stream at /api/jobs/stream feeds the UI dock.

class Job:
    def __init__(self, *, kind: str, title: str, handler, payload: Optional[dict] = None):
        self.id = str(uuid.uuid4())[:8]
        self.kind = kind                  # "ingest_text" | "ingest_file" | "ingest_image"
        self.title = title
        self.status = "queued"            # queued | running | completed | failed | canceled
        self.progress = 0.0               # 0..1
        self.step: Optional[str] = None   # human-readable current step
        self.error: Optional[str] = None
        self.result: Optional[dict] = None
        self.payload = payload or {}      # private — never returned via to_public()
        self.handler = handler
        self.created_at = _utc_now_iso()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.cancel_requested = False

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "step": self.step,
            "error": self.error,
            "result": self.result,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


class JobQueue:
    """Single-worker FIFO. submit() returns immediately. The background thread
    runs jobs serially. Listeners get live events for the SSE stream."""

    RECENT_LIMIT = 50

    def __init__(self):
        self._q: _stdlib_queue.Queue = _stdlib_queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._queue_order: list[str] = []
        self._active_id: Optional[str] = None
        self._recent_ids = collections.deque(maxlen=self.RECENT_LIMIT)
        self._lock = threading.Lock()
        self._listeners: list[_stdlib_queue.Queue] = []
        threading.Thread(target=self._run_worker, daemon=True, name="JobQueueWorker").start()

    def submit(self, *, kind: str, title: str, handler, payload: Optional[dict] = None) -> Job:
        job = Job(kind=kind, title=title, handler=handler, payload=payload)
        with self._lock:
            self._jobs[job.id] = job
            self._queue_order.append(job.id)
        self._q.put(job.id)
        self._notify("job.queued", job)
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status == "queued":
                job.status = "canceled"
                job.finished_at = _utc_now_iso()
                if job.id in self._queue_order:
                    self._queue_order.remove(job.id)
                self._recent_ids.append(job.id)
                self._notify("job.canceled", job)
                return True
            if job.status == "running":
                # Can't cleanly interrupt an in-flight LLM call. Mark a flag the
                # handler can poll between steps if it wants to abort early.
                job.cancel_requested = True
                return True
            return False

    def get(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        return job.to_public() if job else None

    def queue_position(self, job_id: str) -> int:
        with self._lock:
            try:
                return self._queue_order.index(job_id) + 1
            except ValueError:
                return 0

    def snapshot(self) -> dict:
        with self._lock:
            active = self._jobs[self._active_id].to_public() if self._active_id and self._active_id in self._jobs else None
            queued = [self._jobs[i].to_public() for i in self._queue_order if i in self._jobs]
            recent = [self._jobs[i].to_public() for i in reversed(self._recent_ids) if i in self._jobs]
            return {"active": active, "queued": queued, "recent": recent}

    def update_progress(self, job_id: str, *, progress: Optional[float] = None, step: Optional[str] = None):
        job = self._jobs.get(job_id)
        if not job:
            return
        if progress is not None:
            job.progress = max(0.0, min(1.0, float(progress)))
        if step is not None:
            job.step = step
        self._notify("job.progress", job)

    def listen(self) -> _stdlib_queue.Queue:
        q: _stdlib_queue.Queue = _stdlib_queue.Queue(maxsize=256)
        with self._lock:
            self._listeners.append(q)
        return q

    def unlisten(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _notify(self, event: str, job: Job):
        payload = {"event": event, "job": job.to_public()}
        with self._lock:
            dead = []
            for q in self._listeners:
                try:
                    q.put_nowait(payload)
                except _stdlib_queue.Full:
                    dead.append(q)
            for q in dead:
                self._listeners.remove(q)

    def _run_worker(self):
        while True:
            job_id = self._q.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or job.status != "queued":
                    continue
                self._active_id = job.id
                if job.id in self._queue_order:
                    self._queue_order.remove(job.id)
                job.status = "running"
                job.started_at = _utc_now_iso()
            self._notify("job.started", job)
            try:
                result = job.handler(job, self)
                job.result = result if isinstance(result, dict) else {"value": result}
                job.status = "completed"
                job.progress = 1.0
            except Exception as e:
                job.error = str(e)
                job.status = "failed"
                print(f"[BrainOS] job {job.id} ({job.kind}) failed: {e}")
            finally:
                job.finished_at = _utc_now_iso()
                with self._lock:
                    self._active_id = None
                    self._recent_ids.append(job.id)
                self._notify("job.finished", job)


job_queue = JobQueue()


# ── Job handlers ─────────────────────────────────────────────────────────────
# Each handler takes (job, queue) and returns a result dict. The queue arg is
# used to publish step/progress updates the UI dock subscribes to.

def _handler_ingest_text(job: Job, q: JobQueue) -> dict:
    p = job.payload
    q.update_progress(job.id, step="extracting facts", progress=0.15)
    extraction = ingest_agent.extract_from_text(
        p["kind"], p["title"], p["content"], model_override=p.get("model"),
    )
    q.update_progress(job.id, step="reconciling + storing", progress=0.7)
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id, "kind": p["kind"], "title": p["title"],
        "content": p["content"], "url": p.get("url"), "capturedAt": now,
    }
    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
        relationships=extraction.get("relationships", []),
        raw_chunks=_chunk_text(p["content"], max_chars=_MAX_EXTRACTION_CHARS),
    )
    return {
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
        **result,
    }


def _handler_ingest_slack_realtime(job: Job, q: JobQueue) -> dict:
    from slack_mcp.ingest import ingest_slack_document
    from slack_mcp.schemas import SlackSourceDocument

    p = job.payload
    doc = SlackSourceDocument(**p["doc"])
    q.update_progress(job.id, step="extracting Slack decision context", progress=0.15)
    result = ingest_slack_document(
        doc,
        ingest_agent=ingest_agent,
        struct_agent=struct_agent,
        chunk_text=_chunk_text,
        max_extraction_chars=_MAX_EXTRACTION_CHARS,
        utc_now_iso=_utc_now_iso,
        debug_event=_debug_event,
        model=p.get("model"),
    )

    alerts_created: list[dict] = []
    if p.get("ceo_alerts"):
        q.update_progress(job.id, step="routing CEO decision alerts", progress=0.9)
        source_id = result.get("source_id")
        brain = _read_brain()
        source = next(
            (s for s in brain.get("sources", []) if s.get("id") == source_id),
            {"id": source_id, "title": doc.title, "channelId": doc.channel_id, "channelName": doc.channel_name, "threadTs": doc.thread_ts},
        )
        units = [
            u for u in brain.get("units", [])
            if any(ev.get("sourceId") == source_id for ev in (u.get("evidence") or []) if isinstance(ev, dict))
        ]
        alerts_created = decision_alerts.create_for_source(source=source, units=units)
        _debug_event(
            "decision_alerts.created",
            "Created CEO decision alerts from realtime Slack ingest",
            source_id=source_id,
            alerts=len(alerts_created),
        )

    return {
        **result,
        "alerts_created": len(alerts_created),
        "alert_ids": [a["id"] for a in alerts_created],
    }


def _enqueue_slack_realtime_ingest(doc, ceo_alerts: bool) -> dict:
    job = job_queue.submit(
        kind="slack_realtime",
        title=doc.title,
        handler=_handler_ingest_slack_realtime,
        payload={
            "doc": doc.model_dump() if hasattr(doc, "model_dump") else doc.dict(),
            "ceo_alerts": ceo_alerts,
            "model": None,
        },
    )
    return {
        "queued": True,
        "job_id": job.id,
        "status": job.status,
        "queue_position": job_queue.queue_position(job.id),
        "title": job.title,
    }


def _handler_ingest_file(job: Job, q: JobQueue) -> dict:
    p = job.payload
    filename = p["filename"]
    data: bytes = p["data"]
    q.update_progress(job.id, step="extracting text", progress=0.05)
    text = _extract_file_text(filename, data)
    if (
        not text.strip()
        or text.startswith("[PDF has no selectable")
        or text.startswith("[PDF extraction failed")
        or text.startswith("[DOC extraction failed")
        or text.startswith("[DOCX extraction failed")
    ):
        raise RuntimeError(text if text.startswith("[") else "Could not extract any text from the file.")
    chunks = _chunk_text(text, max_chars=_MAX_EXTRACTION_CHARS)
    all_units, all_entities, all_relationships = [], [], []
    for idx, chunk in enumerate(chunks, start=1):
        q.update_progress(
            job.id,
            step=f"extracting facts (chunk {idx}/{len(chunks)})",
            progress=0.1 + 0.6 * (idx / max(len(chunks), 1)),
        )
        ex = ingest_agent.extract_from_text(p["kind"], p["title"], chunk, model_override=p.get("model"))
        all_units.extend(ex.get("units", []))
        all_entities.extend(ex.get("entities", []))
        all_relationships.extend(ex.get("relationships", []))
    used_fallback = False
    if not (all_units or all_entities or all_relationships):
        fb = _fallback_extract_from_document(p["kind"], p["title"], text)
        all_units = fb.get("units", [])
        all_entities = fb.get("entities", [])
        all_relationships = fb.get("relationships", [])
        used_fallback = True
    q.update_progress(job.id, step="reconciling + storing", progress=0.85)
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id, "kind": p["kind"], "title": p["title"],
        "content": text[:2000], "url": p.get("url"), "capturedAt": now,
        "uploadedFilename": filename, "charCount": len(text),
        "chunkCount": len(chunks),
        "extractionMode": "fallback" if used_fallback else "model",
    }
    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=all_units, entities=all_entities,
        relationships=all_relationships, raw_chunks=chunks,
    )
    return {
        "source_id": source_id, "chunks_processed": len(chunks),
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "relationships_extracted": len(all_relationships),
        "fallback_extraction": used_fallback,
        **result,
    }


def _handler_ingest_image(job: Job, q: JobQueue) -> dict:
    p = job.payload
    image_data: bytes = p["data"]
    mime = p.get("mime") or "image/png"
    q.update_progress(job.id, step="describing image (VLM)", progress=0.15)
    description = ingest_agent.describe_image(image_data, mime, model_override=p.get("vlm_model"))
    if not (description or "").strip() or (description or "").startswith("[VLM description unavailable"):
        raise RuntimeError(description or "VLM did not return an image description.")
    q.update_progress(job.id, step="extracting facts", progress=0.55)
    extraction = ingest_agent.extract_from_text(
        f"image/{p['kind']}", p["title"], description,
        model_override=p.get("text_model") or p.get("vlm_model"),
    )
    used_fallback = False
    if not (extraction.get("units") or extraction.get("entities") or extraction.get("relationships")):
        extraction = _fallback_extract_from_document(f"image/{p['kind']}", p["title"], description)
        used_fallback = True
    q.update_progress(job.id, step="reconciling + storing", progress=0.85)
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id, "kind": p["kind"], "title": p["title"],
        "content": description, "url": p.get("url"), "capturedAt": now,
        "imageIngested": True, "imageFilename": p.get("filename"),
        "extractionMode": "fallback" if used_fallback else "model",
    }
    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
        relationships=extraction.get("relationships", []),
        raw_chunks=[description],
    )
    return {
        "source_id": source_id, "vlm_description_chars": len(description),
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
        "fallback_extraction": used_fallback,
        **result,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Code ingest pipeline
# ══════════════════════════════════════════════════════════════════════════════
# Ingests a zip of code OR a single code/doc file. We do NOT embed code bodies
# (that's Cursor's job and a token-cost trap). What we DO extract:
#   • A lightweight file-tree map (path, language, size, category)
#   • Atomic facts from rationale-bearing files (READMEs, ADRs, RFCs,
#     CONTRIBUTING, design docs) via the existing ingest_agent
#   • Ownership facts from CODEOWNERS
#   • Entity ↔ path links so existing entities pick up file references
#
# Output: same shape as other ingest paths (sources/units/entities/relationships
# go into brain.json), plus a codebase summary block on the source record.

_CODE_EXTS = {
    ".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "jsx", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift", ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "c",
    ".h": "c-header", ".hpp": "cpp-header", ".hh": "cpp-header",
    ".scala": "scala", ".clj": "clojure", ".cljs": "clojurescript",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
    ".ml": "ocaml", ".mli": "ocaml", ".fs": "fsharp", ".fsx": "fsharp",
    ".lua": "lua", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".fish": "fish", ".ps1": "powershell",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".sass": "sass", ".less": "less", ".vue": "vue", ".svelte": "svelte",
    ".r": "r", ".R": "r", ".dart": "dart", ".zig": "zig", ".nim": "nim",
    ".jl": "julia", ".sol": "solidity", ".proto": "protobuf",
    ".sql": "sql", ".graphql": "graphql", ".gql": "graphql",
}
_RATIONALE_EXTS = {".md", ".mdx", ".rst", ".adoc", ".org"}
# Note: .txt deliberately excluded — too generic, catches false positives like
# requirements.txt / dependencies.txt / output.txt. Markdown + reStructuredText
# + AsciiDoc + Org-mode are the actual rationale-bearing formats.
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg", ".conf"}
_IGNORE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "env", "__pycache__",
    "build", "dist", "out", ".next", ".cache", ".turbo", ".parcel-cache",
    "target", "vendor", "third_party", ".idea", ".vscode", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "coverage", "htmlcov", ".tox",
    "site-packages", "deps", "_build", ".gradle",
}
_IGNORE_FILES = {
    ".DS_Store", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "uv.lock", "bun.lockb",
}
# Hard cap on a single ingested codebase. Anything past this is silently
# truncated; we emit a `truncated=True` flag on the source record.
_MAX_CODE_FILES = 5000
_MAX_FILE_BYTES = 512 * 1024          # 512 KB per rationale file (sane upper bound)
_MAX_RATIONALE_FILES_EXTRACTED = 80   # cap LLM extraction calls per zip


def _classify_file(path: str) -> dict:
    """Return {category, language} for a given relative path. Category is one of
    'code' | 'doc' | 'config' | 'test' | 'owners' | 'adr' | 'other'."""
    name = os.path.basename(path)
    lower = name.lower()
    ext = os.path.splitext(name)[1].lower()
    pdir = path.lower().replace("\\", "/")

    if name == "CODEOWNERS" or lower == "codeowners":
        return {"category": "owners", "language": "codeowners"}

    # ADR / RFC / decision-log heuristic
    if any(seg in pdir for seg in ("/adr/", "/adrs/", "/rfc/", "/rfcs/",
                                    "/decisions/", "/decision-log/")):
        if ext in _RATIONALE_EXTS:
            return {"category": "adr", "language": "markdown" if ext in {".md", ".mdx"} else ext.lstrip(".")}

    if ext in _RATIONALE_EXTS:
        # Notable doc files get a stronger category for downstream weighting
        if lower in {"readme.md", "readme.mdx", "readme.rst", "readme",
                     "contributing.md", "architecture.md", "design.md",
                     "rationale.md"}:
            return {"category": "doc", "language": "markdown"}
        return {"category": "doc", "language": "markdown" if ext in {".md", ".mdx"} else ext.lstrip(".")}

    if ext in _CODE_EXTS:
        if "/test/" in pdir or "/tests/" in pdir or "/__tests__/" in pdir or "_test." in lower or ".test." in lower or ".spec." in lower:
            return {"category": "test", "language": _CODE_EXTS[ext]}
        return {"category": "code", "language": _CODE_EXTS[ext]}

    if ext in _CONFIG_EXTS or lower in {"dockerfile", "makefile", ".gitignore",
                                          ".dockerignore", ".editorconfig"}:
        return {"category": "config", "language": ext.lstrip(".") or "config"}

    return {"category": "other", "language": ext.lstrip(".") or "binary"}


def _should_skip_path(rel_path: str) -> bool:
    """True if any path segment matches an ignore-dir or the filename is
    in IGNORE_FILES."""
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in _IGNORE_DIRS:
            return True
    if parts and parts[-1] in _IGNORE_FILES:
        return True
    return False


def _walk_zip(zip_bytes: bytes) -> list[dict]:
    """Walk a zip archive in-memory. Returns a list of {path, size, ...class}.
    Skips IGNORE_DIRS/FILES. Truncates at _MAX_CODE_FILES."""
    out: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Detect a common top-level directory prefix (e.g. "my-repo-main/") and
        # strip it so paths look natural to the user.
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = ""
        if names:
            firsts = {n.split("/", 1)[0] for n in names}
            if len(firsts) == 1:
                only = next(iter(firsts))
                if any(n.startswith(only + "/") for n in names):
                    prefix = only + "/"
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
            if not rel or _should_skip_path(rel):
                continue
            cls = _classify_file(rel)
            out.append({
                "path": rel,
                "size": info.file_size,
                "category": cls["category"],
                "language": cls["language"],
            })
            if len(out) >= _MAX_CODE_FILES:
                break
    return out


def _read_zip_member(zip_bytes: bytes, archive_path_candidates: list[str], max_bytes: int = _MAX_FILE_BYTES) -> Optional[str]:
    """Open a zip and return decoded text for the first matching member, or
    None. We pass *candidates* because the zip may carry a top-level prefix."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = set(zf.namelist())
        for cand in archive_path_candidates:
            if cand in members:
                try:
                    with zf.open(cand) as fh:
                        return fh.read(max_bytes).decode("utf-8", errors="replace")
                except Exception:
                    return None
    return None


def _parse_codeowners(text: str) -> list[dict]:
    """Parse a CODEOWNERS file (https://docs.github.com/en/repositories/managing-your-repositories-settings-and-features/customizing-your-repository/about-code-owners).
    Returns list of {pattern, owners[]}. Comments and blank lines skipped."""
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, *owners = parts
        owners = [o for o in owners if o.startswith("@") or "@" in o]
        if owners:
            out.append({"pattern": pattern, "owners": owners})
    return out


def _codeowners_to_units(owners_rules: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn CODEOWNERS rules into atomic ownership units + entities +
    relationships. Each rule like `services/billing/  @sarah` becomes:
      unit:   kind=ownership, statement="services/billing/ is owned by @sarah"
      entity: name="@sarah", kind=person
      rel:    @sarah --owns--> services/billing/"""
    units, entities, rels = [], [], []
    seen_owners: set[str] = set()
    for rule in owners_rules:
        pattern = rule["pattern"]
        for owner in rule["owners"]:
            if owner not in seen_owners:
                entities.append({"name": owner, "kind": "person", "aliases": []})
                seen_owners.add(owner)
            units.append({
                "statement": f"{pattern} is owned by {owner} (per CODEOWNERS).",
                "subject": pattern,
                "kind": "ownership",
                "confidence": 0.95,
                "entities": [owner, pattern],
            })
            rels.append({
                "from": owner, "relation": "owns", "to": pattern,
                "confidence": 0.95,
            })
    return units, entities, rels


def _build_tree_summary(files: list[dict]) -> dict:
    """Aggregate the flat file list into a usable summary: language counts,
    directory rollup, top files. The full path list is stored separately."""
    by_lang: dict[str, int] = collections.defaultdict(int)
    by_category: dict[str, int] = collections.defaultdict(int)
    top_dirs: dict[str, int] = collections.defaultdict(int)
    for f in files:
        by_lang[f["language"]] += 1
        by_category[f["category"]] += 1
        top = f["path"].split("/", 1)[0]
        top_dirs[top] += 1
    return {
        "totalFiles": len(files),
        "byLanguage": dict(sorted(by_lang.items(), key=lambda kv: -kv[1])),
        "byCategory": dict(by_category),
        "topLevelDirs": dict(sorted(top_dirs.items(), key=lambda kv: -kv[1])),
    }


def _link_entities_to_paths(entities: list[dict], file_paths: list[str]) -> dict[str, list[str]]:
    """Heuristic entity↔path linker. For each entity, find paths whose any
    segment slug-matches the entity name. e.g. entity 'billing-service' or
    'Billing' matches 'services/billing/*'."""
    def slugs(s: str) -> list[str]:
        s = s.lower().replace("_", "-")
        return [t for t in re.split(r"[^a-z0-9]+", s) if len(t) > 2]

    path_segments: list[tuple[str, set[str]]] = []
    for p in file_paths:
        segs = set()
        for seg in p.lower().split("/"):
            base = os.path.splitext(seg)[0]
            for tok in re.split(r"[^a-z0-9]+", base):
                if len(tok) > 2:
                    segs.add(tok)
        path_segments.append((p, segs))

    out: dict[str, list[str]] = {}
    for ent in entities:
        name = ent.get("name", "")
        if not name or name.startswith("@"):  # skip CODEOWNERS-style people
            continue
        ent_toks = set(slugs(name))
        if not ent_toks:
            continue
        matched = [p for p, segs in path_segments if ent_toks & segs]
        if matched:
            out[name] = matched[:25]  # cap per entity
    return out


# ── Per-file outline extraction ──────────────────────────────────────────────
# Parses code files LOCALLY to produce a structural outline: classes, functions,
# methods, imports, exports. NO LLM, NO embeddings, NO code-body retrieval.
# This is the "shape" of the code an agent needs to know where to look without
# loading the bodies. Bodies stay Cursor's territory.

import ast as _py_ast

_MAX_OUTLINE_BYTES = 200_000  # files larger than this are skipped (huge minified, etc.)
_MAX_SYMBOLS_PER_FILE = 500


def _outline_python(text: str) -> dict:
    """Use the stdlib ast module — robust + accurate for Python."""
    try:
        tree = _py_ast.parse(text)
    except SyntaxError:
        return {"imports": [], "exports": [], "symbols": [], "_error": "syntax"}
    imports: list[str] = []
    symbols: list[dict] = []

    for node in tree.body:
        if isinstance(node, _py_ast.Import):
            for n in node.names:
                imports.append(n.name)
        elif isinstance(node, _py_ast.ImportFrom):
            mod = ("." * (node.level or 0)) + (node.module or "")
            for n in node.names:
                imports.append(f"{mod}.{n.name}" if mod else n.name)
        elif isinstance(node, _py_ast.FunctionDef) or isinstance(node, _py_ast.AsyncFunctionDef):
            symbols.append({
                "name": node.name,
                "kind": "function",
                "line": node.lineno,
                "async": isinstance(node, _py_ast.AsyncFunctionDef),
            })
        elif isinstance(node, _py_ast.ClassDef):
            children = []
            for sub in node.body:
                if isinstance(sub, (_py_ast.FunctionDef, _py_ast.AsyncFunctionDef)):
                    children.append({
                        "name": sub.name,
                        "kind": "method",
                        "line": sub.lineno,
                        "async": isinstance(sub, _py_ast.AsyncFunctionDef),
                    })
            symbols.append({
                "name": node.name, "kind": "class", "line": node.lineno,
                "bases": [_py_ast.unparse(b) for b in node.bases] if hasattr(_py_ast, "unparse") else [],
                "children": children,
            })
        elif isinstance(node, _py_ast.Assign):
            # Top-level CONSTANTS (uppercase names) — useful signal
            for tgt in node.targets:
                if isinstance(tgt, _py_ast.Name) and tgt.id.isupper() and len(tgt.id) > 1:
                    symbols.append({"name": tgt.id, "kind": "const", "line": node.lineno})

    return {
        "imports": imports[:60],
        "exports": [],  # Python doesn't have explicit exports; everything top-level is "exported"
        "symbols": symbols[:_MAX_SYMBOLS_PER_FILE],
    }


# Regex-based outliners for non-Python languages. These are pragmatic — they
# catch ~90% of declarations without parsing the full grammar. For tighter
# accuracy we'd swap in tree-sitter later.

_TS_PATTERNS = {
    "import":     re.compile(r"""^\s*import\s+(?:[^\"']+from\s+)?["']([^"']+)["']""", re.M),
    "import_alt": re.compile(r"""^\s*const\s+\{?[^=]+\}?\s*=\s*require\(["']([^"']+)["']\)""", re.M),
    "export_default": re.compile(r"^\s*export\s+default\s+(?:function|class|const|async\s+function)\s*(\w+)", re.M),
    "export_named":   re.compile(r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var|type|interface|enum)\s+(\w+)", re.M),
    "function":   re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[<(]", re.M),
    "arrow_func": re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?\(", re.M),
    "class":      re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.M),
    "interface":  re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)", re.M),
    "type_alias": re.compile(r"^\s*(?:export\s+)?type\s+(\w+)\s*=", re.M),
    "enum":       re.compile(r"^\s*(?:export\s+)?enum\s+(\w+)", re.M),
}

def _line_of(text: str, span_start: int) -> int:
    return text.count("\n", 0, span_start) + 1


def _outline_ts(text: str) -> dict:
    imports: list[str] = []
    exports: list[str] = []
    symbols: list[dict] = []
    for m in _TS_PATTERNS["import"].finditer(text):
        imports.append(m.group(1))
    for m in _TS_PATTERNS["import_alt"].finditer(text):
        imports.append(m.group(1))
    for m in _TS_PATTERNS["export_default"].finditer(text):
        exports.append(f"{m.group(1)} (default)")
    for m in _TS_PATTERNS["export_named"].finditer(text):
        exports.append(m.group(1))

    def add(kind: str, pattern: re.Pattern):
        for m in pattern.finditer(text):
            symbols.append({"name": m.group(1), "kind": kind, "line": _line_of(text, m.start())})

    add("function", _TS_PATTERNS["function"])
    add("function", _TS_PATTERNS["arrow_func"])
    add("class",     _TS_PATTERNS["class"])
    add("interface", _TS_PATTERNS["interface"])
    add("type",      _TS_PATTERNS["type_alias"])
    add("enum",      _TS_PATTERNS["enum"])
    # De-dup by (name, kind) — function regex + arrow_func can overlap
    seen = set()
    unique: list[dict] = []
    for s in sorted(symbols, key=lambda s: s["line"]):
        key = (s["name"], s["kind"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return {
        "imports": imports[:60],
        "exports": exports[:40],
        "symbols": unique[:_MAX_SYMBOLS_PER_FILE],
    }


_GO_RE_IMPORT = re.compile(r'^\s*"([^"]+)"', re.M)
_GO_RE_IMPORT_BLOCK = re.compile(r"^\s*import\s*\((.*?)\)", re.M | re.S)
_GO_RE_IMPORT_LINE = re.compile(r'^\s*import\s+"([^"]+)"', re.M)
_GO_RE_FUNC = re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.M)
_GO_RE_TYPE = re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface|=)", re.M)

def _outline_go(text: str) -> dict:
    imports: list[str] = []
    for m in _GO_RE_IMPORT_LINE.finditer(text):
        imports.append(m.group(1))
    for blk in _GO_RE_IMPORT_BLOCK.finditer(text):
        for sub in _GO_RE_IMPORT.finditer(blk.group(1)):
            imports.append(sub.group(1))
    symbols = []
    for m in _GO_RE_FUNC.finditer(text):
        symbols.append({"name": m.group(1), "kind": "function", "line": _line_of(text, m.start())})
    for m in _GO_RE_TYPE.finditer(text):
        symbols.append({"name": m.group(1), "kind": "type", "line": _line_of(text, m.start())})
    symbols.sort(key=lambda s: s["line"])
    return {"imports": imports[:60], "exports": [], "symbols": symbols[:_MAX_SYMBOLS_PER_FILE]}


_RUST_RE_USE = re.compile(r"^\s*use\s+([^;]+);", re.M)
_RUST_RE_FN = re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[<(]", re.M)
_RUST_RE_STRUCT = re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)", re.M)
_RUST_RE_ENUM = re.compile(r"^\s*(?:pub\s+)?enum\s+(\w+)", re.M)
_RUST_RE_TRAIT = re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)", re.M)
_RUST_RE_IMPL = re.compile(r"^\s*impl(?:<[^>]+>)?\s+(?:[^{]+for\s+)?(\w+)", re.M)

def _outline_rust(text: str) -> dict:
    imports = [m.group(1).strip() for m in _RUST_RE_USE.finditer(text)]
    symbols = []
    for kind, pat in [("function", _RUST_RE_FN), ("struct", _RUST_RE_STRUCT),
                       ("enum", _RUST_RE_ENUM), ("trait", _RUST_RE_TRAIT),
                       ("impl", _RUST_RE_IMPL)]:
        for m in pat.finditer(text):
            symbols.append({"name": m.group(1), "kind": kind, "line": _line_of(text, m.start())})
    symbols.sort(key=lambda s: s["line"])
    return {"imports": imports[:60], "exports": [], "symbols": symbols[:_MAX_SYMBOLS_PER_FILE]}


_JAVA_RE_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
_JAVA_RE_CLASS = re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+)*class\s+(\w+)", re.M)
_JAVA_RE_INTERFACE = re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)*interface\s+(\w+)", re.M)
_JAVA_RE_METHOD = re.compile(r"^\s+(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\],?\s]+\s+(\w+)\s*\([^)]*\)\s*(?:throws[^{]+)?\{", re.M)

def _outline_java(text: str) -> dict:
    imports = [m.group(1) for m in _JAVA_RE_IMPORT.finditer(text)]
    symbols = []
    for m in _JAVA_RE_CLASS.finditer(text):
        symbols.append({"name": m.group(1), "kind": "class", "line": _line_of(text, m.start())})
    for m in _JAVA_RE_INTERFACE.finditer(text):
        symbols.append({"name": m.group(1), "kind": "interface", "line": _line_of(text, m.start())})
    for m in _JAVA_RE_METHOD.finditer(text):
        nm = m.group(1)
        if nm in {"if", "for", "while", "switch", "return", "catch"}:
            continue
        symbols.append({"name": nm, "kind": "method", "line": _line_of(text, m.start())})
    symbols.sort(key=lambda s: s["line"])
    return {"imports": imports[:60], "exports": [], "symbols": symbols[:_MAX_SYMBOLS_PER_FILE]}


def _extract_outline(path: str, content: str, language: str) -> Optional[dict]:
    """Dispatch outline extraction by language. Returns None if unsupported or
    parsing fails entirely. Per-language failures (bad syntax in one file)
    return a partial result rather than crashing the whole ingest."""
    if len(content.encode("utf-8", errors="ignore")) > _MAX_OUTLINE_BYTES:
        return {"_skipped": "too_large"}
    try:
        if language == "python":
            return _outline_python(content)
        if language in ("typescript", "tsx", "javascript", "jsx"):
            return _outline_ts(content)
        if language == "go":
            return _outline_go(content)
        if language == "rust":
            return _outline_rust(content)
        if language in ("java", "kotlin"):
            return _outline_java(content)
    except Exception as e:
        return {"_error": str(e)[:200], "imports": [], "exports": [], "symbols": []}
    return None  # unsupported language


# ── Call extraction (no LLM) ─────────────────────────────────────────────────
# Pulls callee names + line numbers from a file. We later resolve callees
# against the codebase symbol index. Anything unresolved is dropped — we only
# keep edges that land inside the same codebase, which is what an agent cares
# about ("who in THIS repo calls foo()").

_MAX_CALLS_PER_FILE = 200

def _calls_python(text: str) -> list[dict]:
    """ast-based call extraction. Captures the enclosing function name so
    edges become caller→callee at function granularity."""
    try:
        tree = _py_ast.parse(text)
    except SyntaxError:
        return []
    out: list[dict] = []

    def callee_name(node) -> Optional[str]:
        if isinstance(node, _py_ast.Name):
            return node.id
        if isinstance(node, _py_ast.Attribute):
            # foo.bar.baz() — we record "baz", the rightmost name
            return node.attr
        return None

    class Visitor(_py_ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            name = callee_name(node.func)
            if name and len(out) < _MAX_CALLS_PER_FILE:
                out.append({
                    "caller": ".".join(self.stack) or "<module>",
                    "callee": name,
                    "line": getattr(node, "lineno", 0),
                })
            self.generic_visit(node)

    Visitor().visit(tree)
    return out


# Regex callees: pragmatic, language-agnostic. Matches `name(` after a word
# boundary; filters out keywords. False positives on `if (x)`, `while (x)` are
# eliminated by the keyword filter.
_CALL_KEYWORDS = {
    "if", "for", "while", "switch", "return", "catch", "throw", "new",
    "await", "async", "yield", "match", "let", "var", "const", "type",
    "import", "export", "function", "class", "interface", "struct", "enum",
    "trait", "impl", "fn", "func", "def", "self", "this", "super",
    "true", "false", "null", "nil", "None", "True", "False",
    "use", "package", "namespace", "module", "in", "of", "is", "as",
    "and", "or", "not", "do", "else", "try", "finally", "with", "from",
}
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]+)\s*\(")


def _calls_regex(text: str) -> list[dict]:
    """Cheap callee extraction for non-Python languages. Caller resolution is
    intentionally weak — we tag every call to '<file>' so the call graph
    answers 'who calls X' (good) but not 'X calls who from inside Y' (lossy
    without proper scope tracking). Tree-sitter would do this properly."""
    out: list[dict] = []
    for m in _CALL_RE.finditer(text):
        name = m.group(1)
        if name in _CALL_KEYWORDS:
            continue
        out.append({
            "caller": "<file>",
            "callee": name,
            "line": text.count("\n", 0, m.start()) + 1,
        })
        if len(out) >= _MAX_CALLS_PER_FILE:
            break
    return out


def _extract_calls(content: str, language: str) -> list[dict]:
    """Dispatch by language. Returns []  for unsupported langs."""
    if len(content) > _MAX_OUTLINE_BYTES:
        return []
    try:
        if language == "python":
            return _calls_python(content)
        if language in ("typescript", "tsx", "javascript", "jsx",
                          "go", "rust", "java", "kotlin"):
            return _calls_regex(content)
    except Exception:
        return []
    return []


# ── Symbol index ─────────────────────────────────────────────────────────────
# Inverts the per-file outlines into {symbol_name: [{path, kind, line}, ...]}
# so "where is BillingService defined?" is one dict lookup.

_MAX_SYMBOL_OCCURRENCES = 8  # cap per symbol name — overflow truncated

def _build_symbol_index(files: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for f in files:
        ol = f.get("outline") or {}
        for s in ol.get("symbols") or []:
            name = s.get("name")
            if not name:
                continue
            occ = idx.setdefault(name, [])
            if len(occ) >= _MAX_SYMBOL_OCCURRENCES:
                continue
            occ.append({"path": f["path"], "kind": s.get("kind", "symbol"),
                          "line": s.get("line", 0)})
            # Also index nested methods (one level)
            for child in (s.get("children") or [])[:8]:
                cname = child.get("name")
                if not cname:
                    continue
                cocc = idx.setdefault(cname, [])
                if len(cocc) >= _MAX_SYMBOL_OCCURRENCES:
                    continue
                cocc.append({"path": f["path"], "kind": child.get("kind", "method"),
                                "line": child.get("line", 0), "parent": name})
    return idx


# ── Import / dependency graph ────────────────────────────────────────────────
# Resolves each file's import strings against the file list to produce
# file → file edges. Anything unresolved is bucketed as "external" so we still
# capture third-party dependency counts.

_MAX_IMPORT_EDGES = 30_000

def _resolve_import_python(spec: str, source_path: str, by_module: dict[str, str]) -> Optional[str]:
    """Resolve a python import like 'pkg.sub.mod' or '..mod.thing' against the
    file list. `by_module` maps dotted module path → file path."""
    if not spec:
        return None
    s = spec.strip()
    if s.startswith("."):
        # relative — anchor at source_path's directory
        base = os.path.dirname(source_path)
        dots = 0
        while dots < len(s) and s[dots] == ".":
            dots += 1
        # First dot = current dir; each extra dot pops one up
        for _ in range(dots - 1):
            base = os.path.dirname(base)
        rest = s[dots:]
        rest_dotted = rest.replace(".", "/")
        target = (base + "/" + rest_dotted).lstrip("/") if rest_dotted else base
        for cand in (target + ".py", target + "/__init__.py", target):
            if cand in by_module.values():
                return cand
        return None
    # absolute
    parts = s.split(".")
    # Try longest prefix first: pkg.sub.mod → pkg/sub/mod.py, pkg/sub.py, etc.
    for n in range(len(parts), 0, -1):
        cand = "/".join(parts[:n])
        if cand + ".py" in by_module.values():
            return cand + ".py"
        if cand + "/__init__.py" in by_module.values():
            return cand + "/__init__.py"
    return None


def _resolve_import_relative_path(spec: str, source_path: str, all_paths: set[str]) -> Optional[str]:
    """Resolve a TS/JS-style relative import like './foo' or '../bar/baz'."""
    if not spec.startswith("."):
        return None
    base = os.path.dirname(source_path)
    target = os.path.normpath(os.path.join(base, spec))
    target = target.replace("\\", "/")
    if target.startswith("./"):
        target = target[2:]
    # Try common extensions / index files
    for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
                  "/index.ts", "/index.tsx", "/index.js", "/index.jsx"):
        cand = target + ext
        if cand in all_paths:
            return cand
    return None


def _build_import_graph(files: list[dict]) -> dict:
    """Return {edges: [{from, to, kind}], external: {spec: count}, stats}."""
    all_paths = {f["path"] for f in files}
    # Build a module → path lookup for python resolution
    by_module: dict[str, str] = {}
    for f in files:
        if f.get("language") == "python":
            p = f["path"]
            mod = p[:-3] if p.endswith(".py") else p
            by_module[mod.replace("/", ".")] = p

    edges: list[dict] = []
    external: dict[str, int] = collections.defaultdict(int)
    seen_edges: set[tuple[str, str]] = set()

    for f in files:
        ol = f.get("outline") or {}
        imports = ol.get("imports") or []
        lang = f.get("language", "")
        src = f["path"]
        for imp in imports:
            target: Optional[str] = None
            if lang == "python":
                target = _resolve_import_python(imp, src, by_module)
            elif lang in ("typescript", "tsx", "javascript", "jsx"):
                target = _resolve_import_relative_path(imp, src, all_paths)
            elif lang == "go":
                # Go imports are usually module paths; only resolve internal ones
                # by matching package directory suffix.
                cand_dir = imp.split("/")[-1] if imp else ""
                if cand_dir:
                    for p in all_paths:
                        if cand_dir in p.split("/") and p.endswith(".go"):
                            target = p
                            break

            if target and target != src:
                key = (src, target)
                if key not in seen_edges and len(edges) < _MAX_IMPORT_EDGES:
                    seen_edges.add(key)
                    edges.append({"from": src, "to": target, "kind": "import"})
            elif not target and imp:
                external[imp] += 1

    # Top external deps (capped)
    top_external = dict(sorted(external.items(), key=lambda kv: -kv[1])[:50])

    # Fan-in / fan-out
    fan_in: dict[str, int] = collections.defaultdict(int)
    fan_out: dict[str, int] = collections.defaultdict(int)
    for e in edges:
        fan_in[e["to"]] += 1
        fan_out[e["from"]] += 1
    hubs = sorted(fan_in.items(), key=lambda kv: -kv[1])[:15]

    return {
        "edges": edges,
        "external": top_external,
        "stats": {
            "internalEdges": len(edges),
            "externalDeps": len(external),
            "hubs": [{"path": p, "fanIn": n} for p, n in hubs],
        },
    }


def _resolve_call_edges(
    raw_calls_by_path: dict[str, list[dict]],
    symbol_index: dict[str, list[dict]],
) -> list[dict]:
    """Turn per-file callee names into resolved edges. Only edges where the
    callee maps to a known symbol in the codebase are kept (anything else is
    a stdlib/external call — noise for an agent)."""
    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for src_path, calls in raw_calls_by_path.items():
        for c in calls:
            callee = c.get("callee")
            occurrences = symbol_index.get(callee or "")
            if not occurrences:
                continue
            # Prefer the unique occurrence; if ambiguous, mark as ambiguous with
            # all candidates as comma-joined. We keep one edge per (src, callee).
            paths = [o["path"] for o in occurrences if o["path"] != src_path]
            if not paths:
                continue
            confidence = 0.9 if len(paths) == 1 else 0.5
            target = paths[0]
            key = (src_path, callee, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "from": src_path,
                "fromFunc": c.get("caller") or "",
                "to": target,
                "callee": callee,
                "line": c.get("line", 0),
                "confidence": confidence,
                "ambiguous": len(paths) > 1,
            })
            if len(edges) >= _MAX_IMPORT_EDGES:
                return edges
    return edges


# ── Module summaries (auto-wiki) ─────────────────────────────────────────────
# One LLM call per top-level directory. Compresses (README + outline summary +
# top symbols) into a single "what this module is" paragraph. Caps prevent
# token blow-up on large repos.

_MAX_MODULE_SUMMARIES = 12
_MODULE_SUMMARY_INPUT_CHARS = 4500


def _build_module_summary_prompt(dir_name: str, files_in_dir: list[dict],
                                    readme_text: Optional[str]) -> str:
    by_lang = collections.Counter(f["language"] for f in files_in_dir)
    top_syms: list[str] = []
    for f in files_in_dir:
        for s in (f.get("outline") or {}).get("symbols") or []:
            top_syms.append(f"{s.get('kind', '?')} {s.get('name', '?')} ({f['path']})")
            if len(top_syms) >= 25:
                break
        if len(top_syms) >= 25:
            break

    parts = [
        f"Directory: {dir_name}/",
        f"Files: {len(files_in_dir)} · languages: {', '.join(f'{k}:{v}' for k, v in by_lang.most_common(5))}",
        f"Notable symbols: {'; '.join(top_syms) if top_syms else '(none extracted)'}",
    ]
    if readme_text:
        parts.append(f"README excerpt:\n{readme_text[:1800]}")
    body = "\n\n".join(parts)
    return body[:_MODULE_SUMMARY_INPUT_CHARS]


def _generate_module_summaries(
    files: list[dict],
    top_level_dirs: dict[str, int],
    file_text_for_path: dict[str, str],
    model_override: Optional[str],
) -> list[dict]:
    """For each top-level dir (capped at _MAX_MODULE_SUMMARIES, by file count),
    produce a 2-3 sentence "what this module does" via the LLM. Failures are
    swallowed per-dir so one bad call doesn't break the ingest."""
    ranked_dirs = sorted(top_level_dirs.items(), key=lambda kv: -kv[1])[:_MAX_MODULE_SUMMARIES]
    out: list[dict] = []
    for dir_name, _count in ranked_dirs:
        files_in_dir = [f for f in files if f["path"].split("/", 1)[0] == dir_name]
        if len(files_in_dir) < 2:  # skip noise (e.g. a single top-level file)
            continue
        # Find a README-ish doc in this dir
        readme_text: Optional[str] = None
        for f in files_in_dir:
            base = os.path.basename(f["path"]).lower()
            if base.startswith("readme") or base in ("contributing.md", "architecture.md"):
                readme_text = file_text_for_path.get(f["path"])
                if readme_text:
                    break

        prompt_body = _build_module_summary_prompt(dir_name, files_in_dir, readme_text)
        try:
            client, model = _resolve_override("extract", model_override)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content":
                        "You write terse, factual descriptions of code modules. "
                        "Two to three sentences. No marketing language. No invented "
                        "function names — only refer to symbols listed in the input."},
                    {"role": "user", "content":
                        f"Summarize this module:\n\n{prompt_body}\n\n"
                        "Output only the summary text."},
                ],
                max_tokens=180,
                temperature=0.1,
            )
            summary = (resp.choices[0].message.content or "").strip()
            if summary:
                out.append({
                    "dir": dir_name,
                    "fileCount": len(files_in_dir),
                    "languages": dict(collections.Counter(f["language"] for f in files_in_dir).most_common(5)),
                    "summary": summary[:800],
                })
        except Exception as e:
            _debug_event("code.module_summary.error", f"Failed for {dir_name}", error=str(e))
            continue
    return out


# ── Code context for /ask ────────────────────────────────────────────────────
# Surfaces code-map signals when the question matches entity↔path links,
# symbols, or module names. Returns a small list of context lines that get
# inlined into the LLM prompt alongside Facts / Graph / Raw excerpts.

def _code_context_for_query(query: str, brain: dict, limit: int = 6) -> list[str]:
    q = (query or "").lower()
    if not q:
        return []
    code_sources = [s for s in brain.get("sources", [])
                     if s.get("kind") == "code" and s.get("codebase")]
    if not code_sources:
        return []

    lines: list[str] = []
    seen: set[str] = set()

    def push(line: str):
        if line and line not in seen and len(lines) < limit:
            seen.add(line)
            lines.append(line)

    q_tokens = {t for t in re.split(r"[^a-z0-9]+", q) if len(t) > 2}

    for src in code_sources:
        cb = src["codebase"]

        # Entity ↔ path matches
        for ent, paths in (cb.get("entityPaths") or {}).items():
            if ent.lower() in q or any(t in q for t in re.split(r"[^a-z0-9]+", ent.lower()) if len(t) > 2):
                shown = ", ".join(paths[:4])
                more = f" (+{len(paths) - 4} more)" if len(paths) > 4 else ""
                push(f"[code] entity '{ent}' is referenced at: {shown}{more}")

        # Symbol index matches
        sidx = cb.get("symbolIndex") or {}
        for name, occurrences in sidx.items():
            if name.lower() in q_tokens or any(name.lower() in t for t in q_tokens):
                first = occurrences[0]
                more = f" (+{len(occurrences) - 1} more)" if len(occurrences) > 1 else ""
                push(f"[code] symbol '{name}' ({first.get('kind', '?')}) defined at {first['path']}:{first.get('line', 0)}{more}")

        # Module summaries — match dir name in query
        for mod in cb.get("moduleSummaries") or []:
            if mod["dir"].lower() in q_tokens:
                push(f"[code] module '{mod['dir']}/' — {mod['summary']}")

    return lines


def _handler_ingest_code(job: Job, q: JobQueue) -> dict:
    """Worker handler for code/zip ingest. Builds a file-tree map, extracts
    rationale from doc-shaped files, parses CODEOWNERS, links entities to
    paths, and stores everything via struct_agent."""
    p = job.payload
    raw_bytes: bytes = p["data"]
    filename: str = p["filename"]
    is_zip = filename.lower().endswith(".zip")
    title = p["title"]

    q.update_progress(job.id, step="walking archive" if is_zip else "classifying file", progress=0.05)

    if is_zip:
        files = _walk_zip(raw_bytes)
    else:
        # Single-file path. Classify it; treat its content as inline rationale
        # if it's a doc-shaped file, else just record metadata.
        files = [{
            "path": filename,
            "size": len(raw_bytes),
            **_classify_file(filename),
        }]

    if not files:
        raise RuntimeError("Archive contained no ingestable files.")

    summary = _build_tree_summary(files)
    file_paths = [f["path"] for f in files]
    truncated = len(files) >= _MAX_CODE_FILES

    # 1. Parse CODEOWNERS if present.
    owners_units, owners_entities, owners_rels = [], [], []
    if is_zip:
        owners_text = _read_zip_member(raw_bytes, [
            "CODEOWNERS",
            "docs/CODEOWNERS", ".github/CODEOWNERS", ".gitlab/CODEOWNERS",
            # also try with the top-prefix-stripped form by re-prefixing
        ])
        if not owners_text:
            # Try with potential top-level prefix
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                for member in zf.namelist():
                    if os.path.basename(member) == "CODEOWNERS":
                        try:
                            owners_text = zf.open(member).read(_MAX_FILE_BYTES).decode("utf-8", errors="replace")
                            break
                        except Exception:
                            pass
        if owners_text:
            rules = _parse_codeowners(owners_text)
            owners_units, owners_entities, owners_rels = _codeowners_to_units(rules)
    q.update_progress(job.id, step=f"parsed CODEOWNERS ({len(owners_units)} rules)", progress=0.2)

    # 2. Extract atomic facts from rationale-bearing files (capped).
    all_units = list(owners_units)
    all_entities = list(owners_entities)
    all_relationships = list(owners_rels)
    raw_chunks: list[str] = []
    rationale_files = [f for f in files if f["category"] in ("doc", "adr")]
    # Cap extraction work — prefer ADRs over generic docs when over the limit.
    rationale_files.sort(key=lambda f: (0 if f["category"] == "adr" else 1, f["path"]))
    rationale_files = rationale_files[:_MAX_RATIONALE_FILES_EXTRACTED]
    extracted_count = 0

    for idx, f in enumerate(rationale_files, start=1):
        q.update_progress(
            job.id,
            step=f"extracting rationale: {f['path']} ({idx}/{len(rationale_files)})",
            progress=0.2 + 0.55 * (idx / max(len(rationale_files), 1)),
        )
        if is_zip:
            text = _read_zip_member(raw_bytes, [f["path"]])
            if not text:
                # Try with top prefix re-added
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    for member in zf.namelist():
                        if member.endswith(f["path"]) and not member.endswith("/"):
                            try:
                                text = zf.open(member).read(_MAX_FILE_BYTES).decode("utf-8", errors="replace")
                                break
                            except Exception:
                                pass
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
        if not text or not text.strip():
            continue

        source_type = "code/adr" if f["category"] == "adr" else "code/doc"
        ex = ingest_agent.extract_from_text(
            source_type=source_type,
            title=f["path"],
            content=text[:_MAX_EXTRACTION_CHARS],
            model_override=p.get("model"),
        )
        new_units = ex.get("units", []) or []
        # Tag every unit with the originating file path in its evidence so
        # downstream consumers (skill diff, agent context) can pinpoint where
        # a decision came from.
        for u in new_units:
            evid = u.get("evidence") or []
            evid.append({"path": f["path"]})
            u["evidence"] = evid
        all_units.extend(new_units)
        all_entities.extend(ex.get("entities", []) or [])
        all_relationships.extend(ex.get("relationships", []) or [])
        raw_chunks.append(text[:_MAX_EXTRACTION_CHARS])
        if new_units or ex.get("entities") or ex.get("relationships"):
            extracted_count += 1

    # 2b. Per-file structural outline. Parses code locally (no LLM) for
    # classes, functions, methods, imports. Adds an `outline` field to each
    # code-category FileEntry. Bodies are NOT stored — only the symbol shape.
    q.update_progress(job.id, step="parsing file outlines", progress=0.74)

    outline_supported = {"python", "typescript", "tsx", "javascript", "jsx",
                         "go", "rust", "java", "kotlin"}
    outline_targets = [
        f for f in files
        if f["category"] in ("code", "test") and f["language"] in outline_supported
    ]
    outlines_built = 0
    # Collected during the outline pass and consumed afterward:
    raw_calls_by_path: dict[str, list[dict]] = {}
    # Cache file text for README-shaped files so module-summary generation
    # doesn't have to re-open the zip.
    readme_text_by_path: dict[str, str] = {}

    def _maybe_collect_for_summaries(f: dict, text: str):
        base = os.path.basename(f["path"]).lower()
        if base.startswith("readme") or base in {"contributing.md", "architecture.md", "design.md", "rationale.md"}:
            readme_text_by_path[f["path"]] = text[:_MAX_FILE_BYTES]

    if is_zip:
        # One pass through the zip — open every needed file at most once.
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            members_by_basename: dict[str, list[str]] = {}
            for member in zf.namelist():
                if not member.endswith("/"):
                    members_by_basename.setdefault(os.path.basename(member), []).append(member)
            # Build a path → archive-member map so we don't re-scan the zip
            path_to_member: dict[str, str] = {}
            for f in outline_targets:
                cands = members_by_basename.get(os.path.basename(f["path"]), [])
                # Prefer the candidate whose suffix matches the relative path
                best = next((m for m in cands if m.endswith(f["path"])), None)
                if best is None and cands:
                    best = cands[0]
                if best is not None:
                    path_to_member[f["path"]] = best

            for idx, f in enumerate(outline_targets):
                member = path_to_member.get(f["path"])
                if not member:
                    continue
                try:
                    text = zf.open(member).read(_MAX_OUTLINE_BYTES + 1).decode("utf-8", errors="replace")
                except Exception:
                    continue
                outline = _extract_outline(f["path"], text, f["language"])
                if outline is not None:
                    f["outline"] = outline
                    outlines_built += 1
                # Call extraction shares the same file read — cheap to piggyback.
                calls = _extract_calls(text, f["language"])
                if calls:
                    raw_calls_by_path[f["path"]] = calls
                if idx % 20 == 0:
                    q.update_progress(
                        job.id,
                        step=f"parsing outlines ({idx + 1}/{len(outline_targets)})",
                        progress=0.74 + 0.04 * (idx / max(len(outline_targets), 1)),
                    )

            # Pull README-shaped files for module summaries (separate small pass).
            for f in files:
                base = os.path.basename(f["path"]).lower()
                if base.startswith("readme") or base in {"contributing.md", "architecture.md", "design.md", "rationale.md"}:
                    member = path_to_member.get(f["path"])
                    if not member:
                        # Re-resolve via basename map
                        cands = members_by_basename.get(os.path.basename(f["path"]), [])
                        member = next((m for m in cands if m.endswith(f["path"])), cands[0] if cands else None)
                    if member:
                        try:
                            readme_text_by_path[f["path"]] = zf.open(member).read(_MAX_FILE_BYTES).decode("utf-8", errors="replace")
                        except Exception:
                            pass
    else:
        # Single-file ingest path
        f = files[0]
        if f["category"] in ("code", "test") and f["language"] in outline_supported:
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                outline = _extract_outline(f["path"], text, f["language"])
                if outline is not None:
                    f["outline"] = outline
                    outlines_built += 1
                calls = _extract_calls(text, f["language"])
                if calls:
                    raw_calls_by_path[f["path"]] = calls
            except Exception:
                pass

    q.update_progress(job.id, step="building symbol index", progress=0.78)

    # 3. Entity ↔ path heuristic links.
    entity_paths = _link_entities_to_paths(all_entities, file_paths)

    # 3b. Symbol index, import graph, resolved call graph.
    symbol_index = _build_symbol_index(files)
    import_graph = _build_import_graph(files)
    q.update_progress(job.id, step="resolving call edges", progress=0.82)
    call_edges = _resolve_call_edges(raw_calls_by_path, symbol_index)

    # 3c. Module summaries (auto-wiki). Skipped on tiny ingests where there's
    # only one top-level dir and a handful of files — the LLM call doesn't pay
    # for itself there.
    module_summaries: list[dict] = []
    if len(files) >= 20 and len(summary["topLevelDirs"]) >= 2:
        q.update_progress(job.id, step="summarizing modules (LLM)", progress=0.85)
        module_summaries = _generate_module_summaries(
            files=files,
            top_level_dirs=summary["topLevelDirs"],
            file_text_for_path=readme_text_by_path,
            model_override=p.get("model"),
        )

    # 4. Build the source record. We store the file list + summary as a
    # codebase block on the source — that's the searchable code map.
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id,
        "kind": "code",
        "title": title,
        "content": f"Codebase: {title} · {summary['totalFiles']} files · "
                   f"languages: {', '.join(list(summary['byLanguage'].keys())[:5])}",
        "url": p.get("url"),
        "capturedAt": now,
        "codebase": {
            **summary,
            "truncated": truncated,
            "rationaleFilesExtracted": extracted_count,
            "outlinesBuilt": outlines_built,
            "files": files,            # full list — outlines embedded per file
            "entityPaths": entity_paths,
            "symbolIndex": symbol_index,
            "importGraph": import_graph,
            "callEdges": call_edges,
            "moduleSummaries": module_summaries,
        },
    }

    q.update_progress(job.id, step="reconciling + storing", progress=0.88)

    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=all_units, entities=all_entities,
        relationships=all_relationships,
        raw_chunks=raw_chunks,
    )

    return {
        "source_id": source_id,
        "total_files": summary["totalFiles"],
        "truncated": truncated,
        "languages": summary["byLanguage"],
        "rationale_files_extracted": extracted_count,
        "outlines_built": outlines_built,
        "codeowners_rules": len(owners_units),
        "entity_paths_linked": len(entity_paths),
        "symbols_indexed": len(symbol_index),
        "import_edges": import_graph["stats"]["internalEdges"],
        "external_deps": import_graph["stats"]["externalDeps"],
        "call_edges": len(call_edges),
        "module_summaries": len(module_summaries),
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "relationships_extracted": len(all_relationships),
        **result,
    }


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
    """Enqueue a text ingest job. Returns immediately with a job_id; subscribe
    to /api/jobs/stream for progress."""
    title = req.title or (req.content.strip().splitlines()[0][:80] if req.content.strip() else f"Untitled {req.kind}")
    _debug_event(
        "ingest.text.enqueue", "Queued text ingestion job",
        title=title, kind=req.kind, url=req.url, model=req.model, chars=len(req.content),
    )
    job = job_queue.submit(
        kind="ingest_text", title=title, handler=_handler_ingest_text,
        payload={"kind": req.kind, "title": title, "content": req.content,
                 "url": req.url, "model": req.model},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


_MAX_EXTRACTION_CHARS = 12_000  # ~3k tokens; keeps prompt well inside 70B context window


def _infer_unit_kind(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("owner", "owned by", "owns ", "responsible for", "maintained by", "led by")):
        return "ownership"
    if any(word in lowered for word in ("must", "required", "requires", "always", "never", "policy", "approval", "approvals")):
        return "policy"
    if any(word in lowered for word in ("step ", "deploy", "run ", "create ", "merge ", "tag ", "restart", "escalate")):
        return "process"
    if any(word in lowered for word in ("decided", "decision", "chose", "selected", "standardized on")):
        return "decision"
    if any(word in lowered for word in ("means", "defined as", "refers to", " is a ", " is an ")):
        return "definition"
    if any(word in lowered for word in ("gotcha", "caveat", "avoid", "fails", "failure", "silently", "unless", "except")):
        return "gotcha"
    return "fact"


def _infer_department(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("api", "service", "deploy", "infra", "database", "pr ", "repo", "on-call", "incident")):
        return "engineering"
    if any(word in lowered for word in ("security", "soc2", "access", "secret", "vulnerability", "audit")):
        return "security"
    if any(word in lowered for word in ("contract", "legal", "nda", "privacy", "compliance", "regulatory")):
        return "legal"
    if any(word in lowered for word in ("invoice", "billing", "budget", "payment", "pricing", "revenue")):
        return "finance"
    if any(word in lowered for word in ("hiring", "pto", "benefits", "performance", "manager", "employee")):
        return "hr"
    if any(word in lowered for word in ("customer", "roadmap", "feature", "release", "ux", "backlog")):
        return "product"
    if any(word in lowered for word in ("sales", "pipeline", "quota", "account", "renewal")):
        return "sales"
    if any(word in lowered for word in ("campaign", "brand", "launch", "content", "comms")):
        return "marketing"
    if any(word in lowered for word in ("vendor", "inventory", "shipping", "warehouse", "procurement")):
        return "operations"
    return "general"


def _infer_sector(department: str) -> str:
    return {
        "engineering": "Engineering",
        "product": "Product",
        "legal": "Legal",
        "finance": "Finance",
        "hr": "HR",
        "operations": "Supply Chain",
    }.get(department, "General")


def _extract_candidate_entities(text: str) -> list[dict]:
    candidates: list[str] = []
    patterns = [
        r"\b[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)+(?:\s+[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)*)*\b",
        r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3}\b",
        r"\b[A-Za-z][A-Za-z0-9_-]*(?:API|DB|SDK|CLI|SVC|svc)\b",
        r"\b[A-Za-z][A-Za-z0-9_-]*(?:\s+(?:team|service|api|database|platform|policy|runbook))\b",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text, flags=re.IGNORECASE if "team|service" in pattern else 0))

    seen: set[str] = set()
    entities: list[dict] = []
    stopwords = {"The", "This", "That", "When", "After", "Before", "All", "Every", "Each"}
    for raw in candidates:
        name = re.sub(r"\s+", " ", raw).strip(" .,:;()[]")
        if not name or name.split()[0] in stopwords:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        lowered = key
        if any(word in lowered for word in ("team", "group")):
            kind = "team"
        elif any(word in lowered for word in ("api", "service", "svc", "db", "database", "platform")):
            kind = "system"
        elif any(word in lowered for word in ("policy", "runbook", "process")):
            kind = "process"
        elif len(name.split()) >= 2 and all(part[:1].isupper() for part in name.split()[:2]):
            kind = "person"
        else:
            kind = "concept"
        entities.append({"name": name, "kind": kind, "aliases": []})
        if len(entities) >= 40:
            break
    return entities


def _fallback_extract_from_document(source_type: str, title: str, text: str) -> dict:
    """
    Last-resort extraction for readable uploaded files when the LLM returns no
    structured JSON. It preserves actionable document sentences as low-confidence
    units instead of reporting a successful zero-unit ingestion.
    """
    normalized = re.sub(r"\r\n?", "\n", text)
    raw_items = re.split(r"(?:\n\s*){2,}|(?<=[.!?])\s+(?=[A-Z0-9])|\n\s*(?:[-*•]|\d+[.)])\s+", normalized)
    candidates: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        sentence = re.sub(r"\s+", " ", item).strip(" -\t\n")
        if len(sentence) < 25 or len(sentence.split()) < 5:
            continue
        if sentence.lower() in seen:
            continue
        seen.add(sentence.lower())
        candidates.append(sentence)
        if len(candidates) >= 24:
            break

    entities = _extract_candidate_entities(text)
    entity_names = [entity["name"] for entity in entities]
    units = []
    for sentence in candidates:
        department = _infer_department(sentence)
        units.append({
            "kind": _infer_unit_kind(sentence),
            "department": department,
            "subject": title,
            "statement": sentence if title.lower() in sentence.lower() else f"{title}: {sentence}",
            "entities": [name for name in entity_names if name.lower() in sentence.lower()][:8],
            "evidence_quote": sentence[:500],
            "confidence": 0.55,
            "sector": _infer_sector(department),
            "valid_from": "",
            "valid_to": "",
            "effective_date": "",
            "observed_at": "",
            "temporal_status": "unknown",
        })

    relationships = []
    for sentence in candidates:
        lowered = sentence.lower()
        match = re.search(r"(.+?)\s+is owned by\s+(.+)", sentence, flags=re.IGNORECASE)
        if match:
            left = match.group(2).strip(" .,:;")
            right = match.group(1).strip(" .,:;")
            verb = "owns"
        else:
            match = re.search(r"(.+?)\s+(?:owns|responsible for|requires|uses|integrates with)\s+(.+)", sentence, flags=re.IGNORECASE)
            if not match:
                continue
            left = match.group(1).strip(" .,:;")
            right = match.group(2).strip(" .,:;")
            verb = "owns"
            if "requires" in lowered:
                verb = "requires"
            elif "uses" in lowered:
                verb = "uses"
            elif "integrates with" in lowered:
                verb = "integrates-with"
        if not (left and right):
            continue
        relationships.append({"from": left[-80:], "relation": verb, "to": right[:80], "confidence": 0.45})
        if len(relationships) >= 12:
            break

    _debug_event(
        "extract.fallback.done",
        "Fallback document extraction produced structured data",
        source_type=source_type,
        title=title,
        units=len(units),
        entities=len(entities),
        relationships=len(relationships),
    )
    return {"entities": entities, "units": units, "relationships": relationships}


def _docx_paragraph_text(para: ET.Element, ns: dict[str, str]) -> str:
    parts: list[str] = []
    for node in para.iter():
        if node.tag == f"{{{ns['w']}}}t":
            parts.append(node.text or "")
        elif node.tag == f"{{{ns['w']}}}tab":
            parts.append("\t")
        elif node.tag == f"{{{ns['w']}}}br":
            parts.append("\n")
    return re.sub(r"[ \t]+\n", "\n", "".join(parts)).strip()


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
                    line = _docx_paragraph_text(para, ns)
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
    """Enqueue a file ingest job. We read the bytes now (so the UploadFile
    handle stays valid) then return immediately with a job_id."""
    data = await file.read()
    filename = file.filename or "upload"
    if not title:
        title = filename.rsplit(".", 1)[0] or filename
    _debug_event(
        "ingest.file.enqueue", "Queued file ingestion job",
        title=title, kind=kind, url=url, model=model,
        filename=file.filename, content_type=file.content_type, bytes=len(data),
    )
    job = job_queue.submit(
        kind="ingest_file", title=title, handler=_handler_ingest_file,
        payload={"kind": kind, "title": title, "url": url, "model": model,
                 "filename": filename, "data": data},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


@app.post("/api/ingest_image")
async def ingest_image(
    title: Optional[str] = Form(None),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),       # VLM model override
    text_model: Optional[str] = Form(None),  # extraction model override
    file: UploadFile = File(...),
):
    """Enqueue an image ingest job (VLM → extraction → store)."""
    image_data = await file.read()
    mime = file.content_type or "image/png"
    if not title:
        fname = file.filename or "image"
        title = fname.rsplit(".", 1)[0] or fname
    _debug_event(
        "ingest.image.enqueue", "Queued image ingestion job",
        title=title, kind=kind, url=url, vlm_model=model, text_model=text_model,
        filename=file.filename, content_type=file.content_type, bytes=len(image_data),
    )
    job = job_queue.submit(
        kind="ingest_image", title=title, handler=_handler_ingest_image,
        payload={"kind": kind, "title": title, "url": url, "filename": file.filename,
                 "data": image_data, "mime": mime,
                 "vlm_model": model, "text_model": text_model},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


@app.post("/api/ingest_code")
async def ingest_code(
    title: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),       # extraction model override
    file: UploadFile = File(...),
):
    """Enqueue a code-ingest job. Accepts:
       • a .zip of a repo (preferred) — full file-tree map + CODEOWNERS +
         ADR/RFC/README rationale extraction
       • a single code/doc file — classification + rationale if applicable
    Does NOT embed code bodies; see _handler_ingest_code for the contract."""
    data = await file.read()
    filename = file.filename or "upload"
    if not title:
        title = filename.rsplit(".", 1)[0] or filename
    _debug_event(
        "ingest.code.enqueue", "Queued code ingestion job",
        title=title, filename=file.filename, content_type=file.content_type,
        bytes=len(data),
    )
    job = job_queue.submit(
        kind="ingest_code", title=title, handler=_handler_ingest_code,
        payload={"title": title, "url": url, "model": model,
                 "filename": filename, "data": data},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "enabled"}


def _env_float(name: str, default: float | None = None) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int | None = None) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _vllm_metrics_base() -> str:
    """
    Endpoint used for vLLM Prometheus stats. The agent demo often runs on a
    dedicated Gemma vLLM server, so let metrics follow that server even when the
    ingestion LLM endpoint is configured separately.
    """
    base = (
        os.getenv("VLLM_METRICS_BASE")
        or os.getenv("AGENT_API_BASE")
        or os.getenv("LLM_API_BASE")
        or os.getenv("VLLM_API_BASE")
        or vllm_url
    ).strip()
    base = base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _vllm_metrics_url() -> str:
    return f"{_vllm_metrics_base()}/metrics"


def _fetch_vllm_prometheus() -> dict:
    """
    Fetch raw Prometheus metrics from vLLM and parse the key gauges/counters.
    vLLM exposes /metrics at the base URL (strip /v1).
    Returns an empty dict if the endpoint is unreachable.
    """
    import urllib.request
    import re

    metrics_url = _vllm_metrics_url()

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
            "vllm_metrics_url": _vllm_metrics_url(),
            "serving_config": {
                "model": os.getenv("AGENT_MODEL_NAME", MODEL_NAME),
                "dtype": os.getenv("VLLM_DTYPE", "bfloat16"),
                "max_model_len": _env_int("VLLM_MAX_MODEL_LEN", 32768),
                "gpu_memory_utilization": _env_float("VLLM_GPU_MEMORY_UTILIZATION", 0.95),
                "max_num_batched_tokens": _env_int("VLLM_MAX_NUM_BATCHED_TOKENS", 8192),
                "max_num_seqs": _env_int("VLLM_MAX_NUM_SEQS", 32),
                "chunked_prefill": _env_bool("VLLM_ENABLE_CHUNKED_PREFILL", True),
                "prefix_caching": _env_bool("VLLM_ENABLE_PREFIX_CACHING", True),
                "auto_tool_choice": _env_bool("VLLM_ENABLE_AUTO_TOOL_CHOICE", True),
                "tool_call_parser": os.getenv("VLLM_TOOL_CALL_PARSER", "hermes"),
            },
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
            "gpu_cache_usage_pct": _g(
                "vllm:gpu_cache_usage_perc",
                "vllm:gpu_cache_usage_percentage",
                "vllm:gpu_cache_usage",
                "vllm:kv_cache_usage_perc",
            ),
            "cpu_cache_usage_pct": _g(
                "vllm:cpu_cache_usage_perc",
                "vllm:cpu_cache_usage_percentage",
                "vllm:cpu_cache_usage",
            ),
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
from slack_mcp.auth import load_slack_config
from slack_mcp.web_poller import (
    run_poller as _run_slack_poller,
    get_poller_status as _get_slack_poller_status,
)


@app.post("/api/slack/resync")
async def slack_resync(limit: int = 50):
    """Backfill recent Slack history into the brain. Used after a brain reset
    so the user isn't left with an empty knowledge base while waiting for the
    poller to pick up new messages.

    For each configured channel:
      1. Fetch the latest `limit` messages from conversations.history
      2. Filter out bot/self/subtype/empty messages
      3. Push each through the realtime ingest pipeline so they land in
         ChromaDB + brain.json with the same shape as polled messages
      4. Reset the poller's last_seen_ts file so future polls keep going from
         here without skipping anything

    Returns a summary of how many messages were fetched and enqueued per
    channel.
    """
    from slack_mcp.web_poller import _bot_token, _build_doc, POLLER_STATE_FILE
    token = _bot_token()
    if not token:
        raise HTTPException(status_code=400, detail="no Slack bot token configured")

    cfg = load_slack_config()
    channels = sorted(
        set(cfg.realtime_ingest_channels) | set(cfg.channel_map.keys())
    )
    # Discover the bot's own user id so we can filter its replies out.
    bot_user_id: str | None = None
    async with httpx.AsyncClient(timeout=15.0) as c:
        try:
            r = await c.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            jj = r.json()
            if jj.get("ok"):
                bot_user_id = jj.get("user_id")
        except Exception:
            pass

    summary: list[dict] = []
    newest_per_channel: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30.0) as c:
        for ch in channels:
            if not cfg.channel_allowed(ch):
                summary.append({"channel_id": ch, "skipped": "not_allowed"})
                continue
            try:
                r = await c.get(
                    "https://slack.com/api/conversations.history",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"channel": ch, "limit": max(1, min(int(limit), 200))},
                )
                j = r.json()
            except Exception as e:
                summary.append({"channel_id": ch, "error": str(e)})
                continue
            if not j.get("ok"):
                summary.append({"channel_id": ch, "error": j.get("error")})
                continue

            messages = j.get("messages") or []
            # Slack returns newest-first; reverse so the brain ingests them
            # in chronological order (and the newest ts is captured last).
            messages.reverse()
            fetched = len(messages)
            enqueued = 0
            department = cfg.department_for_channel(ch)
            ceo_alerts = ch in cfg.ceo_decision_alert_channels
            for m in messages:
                ts = str(m.get("ts") or "")
                if not ts:
                    continue
                newest_per_channel[ch] = ts
                if m.get("subtype") or m.get("bot_id"):
                    continue
                if bot_user_id and m.get("user") == bot_user_id:
                    continue
                text = str(m.get("text") or "").strip()
                if not text:
                    continue
                event_like = {
                    "type": "message",
                    "ts": ts,
                    "thread_ts": m.get("thread_ts"),
                    "user": m.get("user"),
                    "channel": ch,
                    "text": text,
                }
                doc = _build_doc(
                    event=event_like,
                    channel_id=ch,
                    channel_name=ch,
                    department=department,
                    text=text,
                )
                try:
                    _enqueue_slack_realtime_ingest(doc, ceo_alerts)
                    enqueued += 1
                except Exception as e:
                    print(f"[BrainOS] resync enqueue failed for {ch}/{ts}: {e}")
            summary.append({
                "channel_id": ch,
                "fetched": fetched,
                "enqueued": enqueued,
            })

    # Update the poller's last_seen file so it doesn't re-process the same
    # messages on its next tick.
    try:
        POLLER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if POLLER_STATE_FILE.exists():
            try:
                existing = json.loads(POLLER_STATE_FILE.read_text()) or {}
            except Exception:
                existing = {}
        last_seen = existing.get("last_seen_ts") or {}
        last_seen.update(newest_per_channel)
        POLLER_STATE_FILE.write_text(json.dumps({"last_seen_ts": last_seen}, indent=2))
    except Exception as e:
        print(f"[BrainOS] WARNING: could not update poller state file: {e}")

    return {"ok": True, "channels": summary}


@app.get("/api/slack/channels")
async def slack_channels_info():
    """Resolve channel_id → channel_name for every configured channel via
    Slack's conversations.info. Cached for 60s to spare the rate limiter.
    UI uses this to show human-readable channel names everywhere instead of
    the bare C-prefixed IDs."""
    import time as _time
    global _channels_cache, _channels_cache_at  # type: ignore[name-defined]
    now = _time.time()
    try:
        if _channels_cache and (now - _channels_cache_at) < 60.0:
            return {"channels": _channels_cache, "cached": True}
    except NameError:
        pass

    cfg = load_slack_config()
    ids = sorted(
        set(cfg.realtime_ingest_channels)
        | set(cfg.allowed_channels)
        | set(cfg.channel_map.keys())
    )
    # Pick the bot token via the same helper the poller uses.
    from slack_mcp.web_poller import _bot_token
    token = _bot_token()
    out = []
    if token and ids:
        async with httpx.AsyncClient(timeout=10.0) as c:
            for cid in ids:
                try:
                    r = await c.get(
                        "https://slack.com/api/conversations.info",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"channel": cid},
                    )
                    j = r.json()
                    if j.get("ok"):
                        ch = j.get("channel") or {}
                        out.append({
                            "id": cid,
                            "name": ch.get("name") or cid,
                            "is_private": bool(ch.get("is_private")),
                            "topic": (ch.get("topic") or {}).get("value") or None,
                        })
                    else:
                        out.append({"id": cid, "name": cid, "error": j.get("error")})
                except Exception as e:
                    out.append({"id": cid, "name": cid, "error": str(e)})
    else:
        out = [{"id": cid, "name": cid} for cid in ids]

    _channels_cache = out  # type: ignore[name-defined]
    _channels_cache_at = now  # type: ignore[name-defined]
    return {"channels": out, "cached": False}


@app.get("/api/slack/poller/status")
def slack_poller_status():
    """Snapshot of the polling background task — tick count, last poll time,
    dispatch totals, last-seen ts per channel. Cheap; safe to poll from UI."""
    s = _get_slack_poller_status()
    # Make times human-friendly alongside the raw epoch seconds.
    import datetime as _dt
    def _fmt(ts):
        if not ts: return None
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat()
    s["started_at_iso"] = _fmt(s.get("started_at"))
    s["last_poll_at_iso"] = _fmt(s.get("last_poll_at"))
    s["last_dispatch_at_iso"] = _fmt(s.get("last_dispatch_at"))
    if s.get("last_poll_at"):
        s["seconds_since_last_poll"] = round(time.time() - s["last_poll_at"], 2)
    return s

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
    enqueue_realtime_ingest=_enqueue_slack_realtime_ingest,
))


# ── Slack polling fallback ────────────────────────────────────────────────────
# Fires `conversations.history` on a fixed interval for each mapped channel
# and feeds new messages into the same realtime-ingest pipeline as the webhook.
# Use when the Slack app's Event Subscriptions URL can't be pointed at this
# backend (e.g. local dev without a tunnel, or no app collaborator access).
# The poller now waits for credentials at startup instead of bailing — so the
# onboarding UI can light it up later without a backend restart.
@app.on_event("startup")
async def _start_slack_poller() -> None:
    import asyncio as _asyncio
    if os.getenv("SLACK_POLLER_ENABLED", "true").strip().lower() not in ("1", "true", "yes", "on"):
        print("[BrainOS] slack web poller: disabled via SLACK_POLLER_ENABLED")
        return
    try:
        interval = float(os.getenv("SLACK_POLLER_INTERVAL_S", "15"))
    except ValueError:
        interval = 15.0
    _asyncio.create_task(
        _run_slack_poller(
            config_loader=load_slack_config,
            enqueue_fn=_enqueue_slack_realtime_ingest,
            debug_event_fn=_debug_event,
            interval_s=interval,
        )
    )


# ── Onboarding endpoints (customer-facing setup flow) ─────────────────────────
# The frontend reads /state to decide whether to show the onboarding wizard
# or the dashboard. /slack/save lets the wizard wire up Slack with just the
# essentials — bot token + channel IDs — no MCP, no signing secret, no app id.
ONBOARDING_FILE = os.path.join(DATA_DIR, "onboarding.json")
SLACK_TOKEN_FILE = os.path.join(DATA_DIR, "slack", "oauth_tokens.json")
SLACK_CHANNEL_MAP_FILE = os.path.join(DATA_DIR, "slack", "channel_map.json")


def _read_onboarding_record() -> dict:
    try:
        with open(ONBOARDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _write_onboarding_record(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ONBOARDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


_DOC_KINDS = {"doc", "pdf", "file", "text", "code", "image"}


@app.get("/api/onboarding/state")
def onboarding_state():
    """Derived onboarding state — fresh on every request from the actual brain
    + Slack config. Front-end uses this to gate the dashboard.

    "Slack ready" means: we have *some* way to talk to Slack AND at least one
    channel to listen to. The wizard intentionally only collects a bot token
    (xoxb-…) and skips the MCP user token, so cfg.configured (which only
    looks at the MCP access_token) isn't sufficient on its own. A bot token
    discovered by the poller's resolver counts just as much.
    """
    from slack_mcp.web_poller import _bot_token
    brain = _read_brain()
    sources = brain.get("sources", []) or []
    doc_sources = [s for s in sources if (s.get("kind") or "").lower() in _DOC_KINDS]
    cfg = load_slack_config()
    slack_channels = sorted(cfg.realtime_ingest_channels) or sorted(cfg.channel_map.keys()) or sorted(cfg.allowed_channels)
    has_bot_token = bool(_bot_token())
    slack_configured = bool(cfg.configured) or has_bot_token
    docs_ready = len(doc_sources) > 0
    slack_ready = slack_configured and bool(slack_channels)
    record = _read_onboarding_record()
    completed_at = record.get("completedAt")
    return {
        "docsReady": docs_ready,
        "slackReady": slack_ready,
        "docsCount": len(doc_sources),
        "slackChannels": slack_channels,
        "slackConfigured": slack_configured,
        "completedAt": completed_at,
        "complete": bool(completed_at) and docs_ready and slack_ready,
    }


@app.post("/api/onboarding/complete")
def onboarding_complete():
    """Mark onboarding done. Idempotent."""
    record = _read_onboarding_record()
    if not record.get("completedAt"):
        record["completedAt"] = _utc_now_iso()
    _write_onboarding_record(record)
    return record


@app.post("/api/onboarding/reset")
def onboarding_reset():
    """Wipe the completion marker so the wizard shows again. Brain & Slack
    config stay intact."""
    try:
        os.remove(ONBOARDING_FILE)
    except FileNotFoundError:
        pass
    return {"ok": True}


@app.post("/api/onboarding/slack/save")
async def onboarding_save_slack(request: Request):
    """Minimal Slack setup. Requires only a bot token (xoxb-…) and one or
    more channel IDs. Validates against Slack auth.test, persists to JSON,
    bumps env so the poller picks them up on its next cycle."""
    body = await request.json()
    bot_token = str(body.get("bot_token") or "").strip()
    channels = body.get("channels") or []
    if isinstance(channels, str):
        channels = [c.strip() for c in channels.split(",") if c.strip()]
    default_dept = (str(body.get("default_department") or "general")).strip() or "general"

    if not bot_token.startswith("xoxb-"):
        raise HTTPException(status_code=400, detail="bot_token must start with xoxb-")
    if not isinstance(channels, list) or not channels:
        raise HTTPException(status_code=400, detail="channels must be a non-empty list")

    # Validate by calling Slack auth.test. Surfaces invalid tokens immediately
    # to the UI rather than failing silently in the poller.
    async with httpx.AsyncClient(timeout=15.0) as c:
        try:
            r = await c.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            j = r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"slack unreachable: {e}") from e
    if not j.get("ok"):
        raise HTTPException(status_code=400, detail=f"slack auth.test failed: {j.get('error')}")

    bot_user_id = j.get("user_id")
    team_id = j.get("team_id")
    team_name = j.get("team")

    # Persist token + bot user id to JSON. The web poller reads from here when
    # SLACK_BOT_TOKEN env isn't set; auth.py also reads from here for the MCP
    # access token fallback chain.
    os.makedirs(os.path.dirname(SLACK_TOKEN_FILE), exist_ok=True)
    existing = {}
    try:
        with open(SLACK_TOKEN_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f) or {}
    except FileNotFoundError:
        pass
    existing["bot_token"] = bot_token
    existing["bot_user_id"] = bot_user_id
    existing["team_id"] = team_id
    existing["team_name"] = team_name
    with open(SLACK_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    # Map every channel to the chosen default department.
    cmap = {}
    try:
        with open(SLACK_CHANNEL_MAP_FILE, "r", encoding="utf-8") as f:
            cmap = json.load(f) or {}
    except FileNotFoundError:
        pass
    for ch in channels:
        cmap[ch] = cmap.get(ch) or default_dept
    with open(SLACK_CHANNEL_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(cmap, f, indent=2)

    # Bump env so the poller's next config_loader() call sees these channels.
    def _merge_env(key: str, new_items: list[str]) -> None:
        existing_items = {x.strip() for x in (os.environ.get(key) or "").split(",") if x.strip()}
        existing_items.update(new_items)
        os.environ[key] = ",".join(sorted(existing_items))

    _merge_env("SLACK_ALLOWED_CHANNELS", channels)
    _merge_env("SLACK_REALTIME_INGEST_CHANNELS", channels)
    if not os.getenv("SLACK_DEFAULT_DEPARTMENT"):
        os.environ["SLACK_DEFAULT_DEPARTMENT"] = default_dept

    # Backfill the most recent messages for each channel so the brain has
    # context immediately rather than waiting for new traffic.
    backfill_summary = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        for ch in channels:
            try:
                rr = await c.get(
                    "https://slack.com/api/conversations.history",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    params={"channel": ch, "limit": 50},
                )
                jj = rr.json()
                if jj.get("ok"):
                    backfill_summary.append({"channel_id": ch, "fetched": len(jj.get("messages") or [])})
                else:
                    backfill_summary.append({"channel_id": ch, "error": jj.get("error")})
            except Exception as e:
                backfill_summary.append({"channel_id": ch, "error": str(e)})

    return {
        "ok": True,
        "bot_user_id": bot_user_id,
        "team_id": team_id,
        "team_name": team_name,
        "channels": sorted(channels),
        "default_department": default_dept,
        "backfill": backfill_summary,
    }


@app.get("/api/skills_export")
def skills_export(token: str = ""):
    """Return brain state for SKILLS.md generation. Gated by EXPORT_TOKEN if set."""
    if EXPORT_TOKEN and token != EXPORT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing export token.")
    return _read_brain()


# ══════════════════════════════════════════════════════════════════════════════
# Skill diff — "what changed since your agent last loaded the skill"
# ══════════════════════════════════════════════════════════════════════════════
# This is the wedge feature. An agent (or human) passes ?since=<ISO_TIMESTAMP>;
# we return only the structural changes that happened after that point —
# decisions changed, owners changed, ADRs superseded, new facts, new code
# paths, etc. The point is: agents don't need to re-load the full skill on
# every call; they sync the delta. None of Cursor / Cody / Mem0 / Zep / Glean
# expose this shape today.

def _parse_iso(ts: Optional[str]) -> Optional[datetime.datetime]:
    if not ts:
        return None
    try:
        # Accept both Z and +00:00 suffixes
        clean = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.datetime.fromisoformat(clean)
    except Exception:
        return None


def _after(unit_ts: Optional[str], since: Optional[datetime.datetime]) -> bool:
    if since is None:
        return True
    dt = _parse_iso(unit_ts)
    return dt is not None and dt > since


@app.get("/api/skill/diff")
def skill_diff(since: str = "", agent: str = ""):
    """Delta report since `since` (ISO timestamp). Optional `agent` filter for
    future per-agent scoping (currently a no-op — every diff sees all facts).

    Returns:
      {
        since, generatedAt,
        summary: { factsAdded, factsSuperseded, factsDisputed,
                   ownersChanged, decisionsChanged, codeSourcesAdded },
        factsAdded:        [unit, ...]   # new units since `since`
        factsSuperseded:   [{unit, supersededBy, validTo}]
        factsDisputed:     [unit, ...]   # units that *became* disputed in window
        ownersChanged:     [unit, ...]   # ownership-kind units since `since`
        decisionsChanged:  [unit, ...]   # decision-kind units since `since`
        adrsSuperseded:    [unit, ...]   # subset of factsSuperseded with code/adr evidence
        codeSourcesAdded:  [source, ...] # codebase ingests since `since`
        entityPathsTouched:{entity: [paths]}  # union over code sources in window
      }
    """
    since_dt = _parse_iso(since) if since else None
    brain = _read_brain()
    units = brain.get("units", [])

    facts_added = [u for u in units
                   if not u.get("stale")
                   and not u.get("supersededBy")
                   and _after(u.get("createdAt"), since_dt)]

    facts_superseded = [
        {
            "unit": u,
            "supersededBy": u.get("supersededBy"),
            "validTo": u.get("validTo"),
            "supersededAt": u.get("supersededAt"),
        }
        for u in units
        if u.get("supersededBy") and _after(u.get("supersededAt") or u.get("validTo"), since_dt)
    ]

    facts_disputed = [u for u in units
                      if u.get("disputed")
                      and _after(u.get("updatedAt") or u.get("createdAt"), since_dt)]

    owners_changed   = [u for u in facts_added if u.get("kind") == "ownership"]
    decisions_changed = [u for u in facts_added if u.get("kind") == "decision"]

    # An ADR supersession is a superseded fact whose evidence path looks like
    # an ADR (segments contain adr/adrs/rfc/decisions). Same heuristic as
    # _classify_file.
    def _is_adr_evidence(unit: dict) -> bool:
        for ev in unit.get("evidence", []) or []:
            path = (ev.get("path") or "").lower().replace("\\", "/")
            if any(s in path for s in ("/adr/", "/adrs/", "/rfc/", "/rfcs/",
                                       "/decisions/", "/decision-log/")):
                return True
        return False

    adrs_superseded = [s for s in facts_superseded if _is_adr_evidence(s["unit"])]

    # Code source deltas — codebases ingested in the window
    code_sources_added = [
        s for s in brain.get("sources", [])
        if s.get("kind") == "code" and _after(s.get("capturedAt"), since_dt)
    ]
    entity_paths_touched: dict[str, list[str]] = {}
    for s in code_sources_added:
        cb = s.get("codebase") or {}
        for ent, paths in (cb.get("entityPaths") or {}).items():
            entity_paths_touched.setdefault(ent, []).extend(paths)
    # de-dup
    for ent, paths in list(entity_paths_touched.items()):
        entity_paths_touched[ent] = sorted(set(paths))

    return {
        "since": since or None,
        "agent": agent or None,
        "generatedAt": _utc_now_iso(),
        "summary": {
            "factsAdded": len(facts_added),
            "factsSuperseded": len(facts_superseded),
            "factsDisputed": len(facts_disputed),
            "ownersChanged": len(owners_changed),
            "decisionsChanged": len(decisions_changed),
            "adrsSuperseded": len(adrs_superseded),
            "codeSourcesAdded": len(code_sources_added),
            "entityPathsTouched": len(entity_paths_touched),
        },
        "factsAdded": facts_added,
        "factsSuperseded": facts_superseded,
        "factsDisputed": facts_disputed,
        "ownersChanged": owners_changed,
        "decisionsChanged": decisions_changed,
        "adrsSuperseded": adrs_superseded,
        "codeSourcesAdded": code_sources_added,
        "entityPathsTouched": entity_paths_touched,
    }


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


# ══════════════════════════════════════════════════════════════════════════════
# CEO decision alert endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/decision-alerts")
def list_decision_alerts(include_closed: bool = False):
    return {
        "alerts": decision_alerts.list(include_closed=include_closed),
        "min_confidence": _decision_alert_min_confidence(),
    }


@app.get("/api/decision-alerts/stream")
def stream_decision_alerts():
    listener = decision_alerts.listen()

    def gen():
        try:
            yield f"data: {json.dumps({'event': 'snapshot', 'alerts': decision_alerts.list()})}\n\n"
            while True:
                try:
                    msg = listener.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except _stdlib_queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            decision_alerts.unlisten(listener)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/decision-alerts/{alert_id}/ack")
def acknowledge_decision_alert(alert_id: str):
    alert = decision_alerts.update_status(alert_id, "acknowledged")
    if not alert:
        raise HTTPException(status_code=404, detail="decision alert not found")
    return {"ok": True, "alert": alert}


@app.post("/api/decision-alerts/{alert_id}/dismiss")
def dismiss_decision_alert(alert_id: str):
    alert = decision_alerts.update_status(alert_id, "dismissed")
    if not alert:
        raise HTTPException(status_code=404, detail="decision alert not found")
    return {"ok": True, "alert": alert}


@app.delete("/api/clear")
def clear_all():
    """Hard reset of the entire RAG pipeline:
      • ChromaDB collection (sysdb row + segment .bin files via Chroma's API)
      • Any orphan segment dirs left behind by previous crashes
      • brain.json
      • uploads/ingested/snapshots dirs
      • in-memory BM25 + entity indexes

    We deliberately do NOT manually delete chroma.sqlite3 — Chroma holds an
    open SQLite handle to it, and yanking the file out from under that handle
    leaves the next operation hitting a schema-less DB ("no such table:
    collections"). Instead we use Chroma's own delete_collection() + reset()
    which clean up .bin files via the segment manager."""
    global collection
    removed: list[str] = []

    # Snapshot the active collection's segment dirs BEFORE delete_collection so
    # we know what to expect on disk afterwards (used to find true orphans in
    # step 4).
    chroma_subdirs_before: set[str] = set()
    if os.path.isdir(CHROMA_PATH):
        chroma_subdirs_before = {
            e for e in os.listdir(CHROMA_PATH)
            if os.path.isdir(os.path.join(CHROMA_PATH, e))
        }

    # 1. Drop the collection. Chroma's segment manager removes the segment
    # directory on disk (data_level0.bin, header.bin, length.bin,
    # link_lists.bin) AND the sysdb row.
    try:
        chroma_client.delete_collection("brainos_knowledge")
        removed.append("chroma:brainos_knowledge")
    except Exception as e:
        # Already gone / never existed — fine, continue.
        print(f"[BrainOS] delete_collection skipped: {e}")

    # 2. Reset the rest of the sysdb (catches any orphan collections from
    # earlier crashes). With allow_reset=True this is non-destructive to the
    # client's connection — sqlite tables are dropped and recreated empty.
    try:
        chroma_client.reset()
    except Exception as e:
        print(f"[BrainOS] chroma_client.reset() skipped: {e}")

    # 3. Recreate the collection on the SAME client. Building a new
    # PersistentClient would hit chromadb's SharedSystemClient cache and
    # return a stale handle ("readonly database") — bad.
    collection = chroma_client.get_or_create_collection(
        name="brainos_knowledge",
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    # 4. Defensive: remove any UUID-shaped segment dirs that existed BEFORE
    # the reset and weren't cleaned up by Chroma (true orphans — usually from
    # an interrupted previous reset). Safe to rmtree because they're no
    # longer referenced by any collection in the freshly-reset sysdb.
    if os.path.isdir(CHROMA_PATH):
        chroma_subdirs_after: set[str] = {
            e for e in os.listdir(CHROMA_PATH)
            if os.path.isdir(os.path.join(CHROMA_PATH, e))
        }
        # Anything that existed before but Chroma didn't touch during reset is
        # an orphan. Belt-and-suspenders only — the common case has no orphans.
        for entry in chroma_subdirs_before & chroma_subdirs_after:
            if len(entry) != 36:  # only UUID-shaped names
                continue
            full = os.path.join(CHROMA_PATH, entry)
            try:
                shutil.rmtree(full)
                removed.append(full)
            except Exception as e:
                print(f"[BrainOS] WARNING: could not remove orphan {full}: {e}")

    # 5. brain.json + decision alerts
    if os.path.exists(BRAIN_JSON):
        try:
            os.remove(BRAIN_JSON)
            removed.append(BRAIN_JSON)
        except Exception as e:
            print(f"[BrainOS] WARNING: could not remove {BRAIN_JSON}: {e}")
    if os.path.exists(DECISION_ALERTS_JSON):
        try:
            os.remove(DECISION_ALERTS_JSON)
            removed.append(DECISION_ALERTS_JSON)
        except Exception as e:
            print(f"[BrainOS] WARNING: could not remove {DECISION_ALERTS_JSON}: {e}")

    # 6. uploads / ingested / snapshots — ingest artifacts
    for sub in ("uploads", "ingested", "snapshots"):
        path = os.path.join(DATA_DIR, sub)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                removed.append(path)
            except Exception as e:
                print(f"[BrainOS] WARNING: could not remove {path}: {e}")

    # 7. Fresh empty brain.json so the frontend sees a clean state.
    empty_state = {
        "sources": [], "entities": [], "units": [],
        "relationships": [], "rawChunks": [],
    }
    _write_brain(empty_state)

    # 8. In-memory BM25 + entity indexes (the BM25 index would otherwise still
    # hold references to the deleted units).
    _build_indexes(empty_state)

    return {"ok": True, "cleared": True, "removed": removed}


# ══════════════════════════════════════════════════════════════════════════════
# Job queue HTTP endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/jobs")
def list_jobs():
    """Return {active, queued[], recent[]}. Cheap; safe to call every few seconds
    as a fallback if SSE isn't available."""
    return job_queue.snapshot()


@app.get("/api/jobs/stream")
def stream_jobs():
    """Server-Sent Events stream of job lifecycle events. The UI dock subscribes
    via EventSource. Sends an initial snapshot, then live deltas, with a 15s
    heartbeat so reverse proxies don't time the connection out."""
    listener = job_queue.listen()

    def gen():
        try:
            yield f"data: {json.dumps({'event': 'snapshot', 'snapshot': job_queue.snapshot()})}\n\n"
            while True:
                try:
                    msg = listener.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except _stdlib_queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            job_queue.unlisten(listener)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # tell nginx not to buffer SSE
            "Connection": "keep-alive",
        },
    )


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    j = job_queue.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    return j


@app.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str):
    ok = job_queue.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="job not cancelable (finished or unknown)")
    return {"ok": True, "canceled": job_id}


# ══════════════════════════════════════════════════════════════════════════════
# BrainOS Autonomous Agent — Gemma 4 on vLLM
# ══════════════════════════════════════════════════════════════════════════════

# BrainOS Agent feature is kept in the codebase, but backend wiring is disabled.
# from brainos_agent import get_agent, init_agent


def _agent_ask_brain(question: str) -> dict:
    query = (question or "").strip()
    if not query:
        raise ValueError("No question was provided to ask_brain.")

    result = exec_agent.execute(query)
    return {
        "answer": result.get("answer", ""),
        "retrieved_ids": result.get("retrieved_ids", []),
        "retrieved_docs": result.get("retrieved_docs", [])[:3],
        "latency_ms": result.get("latency_ms"),
        "retrieval_mode": result.get("retrieval_mode"),
    }


def _agent_ingest_text(text: str, title: str = "Agent Ingestion") -> dict:
    content = (text or "").strip()
    if not content:
        raise ValueError("No text was provided to ingest.")

    source_title = (title or "").strip() or content.splitlines()[0][:80] or "Agent Ingestion"
    job = job_queue.submit(
        kind="ingest_text",
        title=source_title,
        handler=_handler_ingest_text,
        payload={
            "kind": "agent",
            "title": source_title,
            "content": content,
            "url": None,
            "model": None,
        },
    )
    return {
        "queued": True,
        "job_id": job.id,
        "status": job.status,
        "queue_position": job_queue.queue_position(job.id),
        "title": source_title,
        "message": "Ingestion job queued. The BrainOS job dock will show extraction and reconciliation progress.",
    }


def _agent_analyze_gaps() -> dict:
    brain = _read_brain()
    units = [u for u in brain.get("units", []) if not u.get("stale") and not u.get("supersededBy")]
    entities = brain.get("entities", [])
    rels = brain.get("relationships", [])
    gaps = []
    OWNER_VERBS = {"owns", "manages", "governs"}
    owned_targets = {r["to"].lower() for r in rels if r.get("relation", "").lower() in OWNER_VERBS}
    for e in entities:
        if e["kind"] in ("system", "product", "team") and e["name"].lower() not in owned_targets:
            gaps.append({"severity": "high", "kind": "missing_owner", "entity": e["name"],
                         "message": f"No documented owner for {e['kind']} '{e['name']}'."})
    subjects = {u["subject"].lower() for u in units if u.get("subject")}
    mentioned = {n.lower() for u in units for n in u.get("entities", [])}
    for name in mentioned - subjects:
        if name and name not in owned_targets and len(name) > 2:
            ent = next((e for e in entities if e["name"].lower() == name), None)
            if ent:
                gaps.append({"severity": "medium", "kind": "undescribed_entity", "entity": ent["name"],
                             "message": f"'{ent['name']}' is mentioned but never described directly."})
    for u in units:
        if u.get("disputed"):
            gaps.append({"severity": "high", "kind": "open_dispute", "entity": u.get("subject", ""),
                         "message": f"Disputed claim: {u.get('statement', '')}"})
    sev_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: sev_order.get(g["severity"], 3))
    return {"gaps": gaps[:20], "total": len(gaps),
            "counts": {"high": sum(1 for g in gaps if g["severity"] == "high"),
                       "medium": sum(1 for g in gaps if g["severity"] == "medium"),
                       "low": sum(1 for g in gaps if g["severity"] == "low")}}


def _agent_get_graph_summary(entity_filter: str = "") -> dict:
    brain = _read_brain()
    entities = brain.get("entities", [])
    rels = brain.get("relationships", [])
    units = [u for u in brain.get("units", []) if not u.get("stale")]
    if entity_filter:
        ef = entity_filter.lower()
        entities = [e for e in entities if ef in e["name"].lower()]
        rels = [r for r in rels if ef in r.get("from", "").lower() or ef in r.get("to", "").lower()]
    by_kind: dict = {}
    for e in entities:
        by_kind.setdefault(e["kind"], []).append(e["name"])
    sample_rels = [f"{r['from']} --{r.get('relation', r.get('verb', '?'))}--> {r['to']}" for r in rels[:15]]
    return {
        "entity_count": len(entities),
        "relationship_count": len(rels),
        "unit_count": len(units),
        "entities_by_kind": {k: v[:10] for k, v in by_kind.items()},
        "sample_relationships": sample_rels,
    }


def _agent_export_skills(department: str = "") -> dict:
    """
    Calls the real /api/skills Next.js endpoint which runs generateSkills() —
    the full 650-line TypeScript implementation with agent rules, ownership routing,
    gotchas, temporal notes, knowledge graph relationships, source index, confidence
    filtering, and code map. Falls back to a minimal Python version if frontend is unreachable.
    """
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    url = f"{FRONTEND_URL}/api/skills"
    if department:
        valid_depts = {"engineering","product","legal","finance","hr","sales","marketing","operations","security","general"}
        dept_clean = department.strip().lower()
        if dept_clean in valid_depts:
            url += f"?department={dept_clean}"

    try:
        resp = httpx.get(url, timeout=15.0)
        resp.raise_for_status()
        skills_md = resp.text
        # Count units from brain as metadata
        brain = _read_brain()
        active_units = [u for u in brain.get("units", []) if not u.get("stale") and not u.get("supersededBy")]
        if department:
            dept_clean = department.strip().lower()
            dept_units = [u for u in active_units if u.get("department", "").lower() == dept_clean]
            unit_count = len(dept_units)
        else:
            unit_count = len(active_units)
        return {
            "department": department or "all",
            "unit_count": unit_count,
            "skills_md": skills_md,
            "source": "generateSkills (full)",
            "download_url": url,
        }
    except Exception as e:
        # Fallback: minimal Python version when frontend is unreachable
        brain = _read_brain()
        units = [u for u in brain.get("units", []) if not u.get("stale") and not u.get("supersededBy")]
        if department:
            dept_clean = department.strip().lower()
            units = [u for u in units if u.get("department", "").lower() == dept_clean]

        KIND_ORDER = ["ownership", "policy", "process", "gotcha", "decision", "definition", "fact"]
        by_kind: dict = {}
        for u in units:
            by_kind.setdefault(u.get("kind", "fact"), []).append(u)

        lines = [
            f"# Skill: {(department or 'Company').title()} Knowledge Memory",
            "",
            f"Department: {department or 'all'}  |  Units: {len(units)}",
            "",
            "## Agent Rules",
            "",
            "- Use this skill as company-specific operational memory, not general advice.",
            "- Prefer current facts over historical or expired ones.",
            "- Do not invent owners, approvals, dates, or prices not listed here.",
            "",
        ]
        for kind in KIND_ORDER:
            kind_units = by_kind.get(kind, [])
            if not kind_units:
                continue
            lines.append(f"## {kind.title()}s")
            lines.append("")
            for u in kind_units[:20]:
                subj = u.get("subject", "")
                stmt = u.get("statement", "")
                conf = u.get("confidence", 0)
                lines.append(f"- {subj}: {stmt}  (confidence: {conf:.2f})")
            lines.append("")

        rels = brain.get("relationships", [])
        if rels:
            lines.append("## Knowledge Graph Relationships")
            lines.append("")
            for r in rels[:30]:
                lines.append(f"- {r.get('from','')} --{r.get('relation', r.get('verb','?'))}--> {r.get('to','')}")
            lines.append("")

        return {
            "department": department or "all",
            "unit_count": len(units),
            "skills_md": "\n".join(lines),
            "source": "fallback (frontend unreachable)",
            "error": str(e),
        }


def _agent_detect_failures() -> dict:
    brain = _read_brain()
    units = [u for u in brain.get("units", []) if not u.get("stale")]
    failures = [u for u in units if u.get("kind") == "gotcha" or u.get("disputed")]
    return {
        "failure_count": len(failures),
        "failures": [{"subject": u.get("subject"), "statement": u.get("statement"), "kind": u.get("kind")}
                     for u in failures[:10]],
    }


def _agent_get_metrics() -> dict:
    prom = _fetch_vllm_prometheus()
    brain = _read_brain()

    def _g(*keys, default=None):
        for k in keys:
            if k in prom:
                return prom[k]
        return default

    return {
        "tokens_per_second": _g("vllm:avg_generation_throughput_toks_per_s", default=0),
        "gpu_cache_usage": _g("vllm:gpu_cache_usage_perc", default=0),
        "pending_requests": _g("vllm:num_requests_waiting", default=0),
        "running_requests": _g("vllm:num_requests_running", default=0),
        "unit_count": len(brain.get("units", [])),
        "entity_count": len(brain.get("entities", [])),
    }


# _brainos_agent = init_agent({
#     "ask_brain": _agent_ask_brain,
#     "ingest_text": _agent_ingest_text,
#     "analyze_gaps": _agent_analyze_gaps,
#     "get_graph_summary": _agent_get_graph_summary,
#     "export_skills": _agent_export_skills,
#     "detect_failures": _agent_detect_failures,
#     "get_metrics": _agent_get_metrics,
# })
#
#
# class AgentRequest(BaseModel):
#     session_id: Optional[str] = None
#     message: str
#
#
# @app.post("/api/agent")
# def agent_chat(req: AgentRequest):
#     session_id = req.session_id or str(uuid.uuid4())
#     try:
#         response = _brainos_agent.run(session_id=session_id, user_message=req.message)
#         return response.to_dict()
#     except Exception as e:
#         raise HTTPException(status_code=503, detail=f"Agent error: {e}")
#
#
# @app.delete("/api/agent/session/{session_id}")
# def clear_agent_session(session_id: str):
#     _brainos_agent.clear_session(session_id)
#     return {"ok": True, "cleared": session_id}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
