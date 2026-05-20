"""Model routing: provider selection, per-task (client, model) resolution."""
from __future__ import annotations
import os
from config import (
    LLM_PROVIDER_ENV, LLM_API_BASE, VLM_API_BASE,
    CLAUDE_API_KEY, CLAUDE_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
)
import httpx
from core.logging import _debug_event
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
# Supported providers (set via LLM_PROVIDER or auto-detected from keys):
#
#   LLM_PROVIDER=claude   →  Anthropic Claude API      (CLAUDE_API_KEY required)
#   LLM_PROVIDER=openai   →  OpenAI API                (OPENAI_API_KEY required)
#   LLM_PROVIDER=custom   →  Any OpenAI-compatible endpoint (LLM_API_BASE required)
#
# Auto-detection priority when LLM_PROVIDER is unset:
#   Claude key present  →  claude
#   OpenAI key present  →  openai
#   LLM_API_BASE reachable → custom
#   (fallback: custom with warning)
_provider_env = os.getenv("LLM_PROVIDER", "").strip().lower()

_raw_llm_url  = (os.getenv("LLM_API_BASE") or os.getenv("VLLM_API_BASE") or "").strip()
_raw_vlm_url  = (os.getenv("VLM_API_BASE") or "").strip()
_claude_key   = CLAUDE_API_KEY
_claude_model = CLAUDE_MODEL
_openai_key   = OPENAI_API_KEY
_openai_model = OPENAI_MODEL

# True for managed API providers (Claude, OpenAI) — disables per-task endpoint overrides.
_USING_MANAGED_API = False
_USING_CLAUDE_FALLBACK = False  # kept for backwards-compat with health route


def _choose_provider() -> str:
    if _provider_env in ("claude", "openai", "custom"):
        return _provider_env
    # Auto-detect: Claude > OpenAI > reachable custom endpoint
    if _claude_key:
        return "claude"
    if _openai_key:
        return "openai"
    if _raw_llm_url and _probe_endpoint(_raw_llm_url):
        return "custom"
    return "custom"  # last resort — server starts but calls will fail


_provider = _choose_provider()

if _provider == "custom":
    if not _raw_llm_url:
        print("[BrainOS] WARNING: LLM_PROVIDER=custom but LLM_API_BASE is empty — ingestion/ask will fail")
    vllm_url   = _raw_llm_url or "http://localhost:8000/v1"
    vlm_url    = _raw_vlm_url or vllm_url
    llm_client = VLLMClient(base_url=vllm_url)
    vlm_client = VLLMClient(base_url=vlm_url)
    print(f"[BrainOS] Provider: custom endpoint ({vllm_url})")

elif _provider == "claude":
    if not _claude_key:
        print("[BrainOS] WARNING: LLM_PROVIDER=claude but CLAUDE_API_KEY is empty — ingestion/ask will fail")
    _USING_MANAGED_API = True
    _USING_CLAUDE_FALLBACK = True
    vllm_url   = "https://api.anthropic.com/v1"
    vlm_url    = vllm_url
    llm_client = ClaudeAPIClient(api_key=_claude_key or "missing", model=_claude_model)
    vlm_client = ClaudeAPIClient(api_key=_claude_key or "missing", model=_claude_model)
    print(f"[BrainOS] Provider: Claude API ({_claude_model})")

elif _provider == "openai":
    if not _openai_key:
        print("[BrainOS] WARNING: LLM_PROVIDER=openai but OPENAI_API_KEY is empty — ingestion/ask will fail")
    _USING_MANAGED_API = True
    _USING_CLAUDE_FALLBACK = True  # same behaviour: no per-task endpoint overrides
    vllm_url   = "https://api.openai.com/v1"
    vlm_url    = vllm_url
    # VLLMClient auto-reads OPENAI_API_KEY and adds Authorization: Bearer header
    llm_client = VLLMClient(base_url=vllm_url)
    vlm_client = VLLMClient(base_url=vlm_url)
    print(f"[BrainOS] Provider: OpenAI API ({_openai_model})")


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


# Model name defaults are provider-aware so users only need one env var.
if _provider == "claude":
    _model_env     = os.getenv("MODEL_NAME", _claude_model)
    _vlm_model_env = os.getenv("VLM_MODEL_NAME", _claude_model)
elif _provider == "openai":
    _model_env     = os.getenv("MODEL_NAME", _openai_model)
    _vlm_model_env = os.getenv("VLM_MODEL_NAME", _openai_model)
else:
    _model_env     = os.getenv("MODEL_NAME", "llava-hf/llava-v1.6-mistral-7b-hf")
    _vlm_model_env = os.getenv("VLM_MODEL_NAME", "llava-hf/llava-v1.6-mistral-7b-hf")

# For managed API providers (Claude, OpenAI) we trust the configured model name
# and skip the endpoint probe — _resolve_model queries /models which would
# return unrelated models (e.g. embedding models) and auto-select the wrong one.
_OPENAI_KNOWN_MODELS = {
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
    "gpt-3.5-turbo", "o1", "o1-mini", "o3", "o3-mini",
}
_CLAUDE_KNOWN_MODELS_PREFIX = ("claude-",)

if _USING_MANAGED_API:
    MODEL_NAME     = _model_env
    VLM_MODEL_NAME = _vlm_model_env
    # Warn on obviously wrong model names for the selected provider
    if _provider == "openai" and MODEL_NAME not in _OPENAI_KNOWN_MODELS:
        print(f"[BrainOS] WARNING: OPENAI_MODEL='{MODEL_NAME}' is not a recognised OpenAI model ID.")
        print(f"[BrainOS]          Valid options: {sorted(_OPENAI_KNOWN_MODELS)}")
        print(f"[BrainOS]          Set OPENAI_MODEL=gpt-4o-mini in .env and restart.")
    elif _provider == "claude" and not MODEL_NAME.startswith(_CLAUDE_KNOWN_MODELS_PREFIX):
        print(f"[BrainOS] WARNING: CLAUDE_MODEL='{MODEL_NAME}' does not look like a Claude model ID (expected 'claude-...').")
    print(f"[BrainOS] MODEL_NAME={MODEL_NAME} (managed API — skipping model probe)")
else:
    MODEL_NAME     = _resolve_model(llm_client, "MODEL_NAME", _model_env)
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
        # For managed API providers (Claude, OpenAI), ignore per-task API_BASE overrides
        if _USING_MANAGED_API:
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

