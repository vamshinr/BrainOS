"""Health check and model listing endpoints."""
from __future__ import annotations
from fastapi import APIRouter
from storage.chroma import collection, EMBEDDING_BACKEND
from storage.brain import _read_brain
from clients.router import router as model_router, llm_client, vlm_client, vllm_url, vlm_url, _USING_CLAUDE_FALLBACK, TASKS
from clients.vllm import VLLMClient

router = APIRouter()

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
        c, _ = model_router.get(task)
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

@router.get("/api/models")
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


@router.get("/health")
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


