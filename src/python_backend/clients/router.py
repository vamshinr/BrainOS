"""Model routing: provider selection, per-task (client, model) resolution."""
from __future__ import annotations
import os
from config import (
    LLM_PROVIDER_ENV, LLM_API_BASE, VLM_API_BASE,
    CLAUDE_API_KEY, CLAUDE_MODEL,
)
from clients.vllm import VLLMClient
from clients.claude import ClaudeAPIClient

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

