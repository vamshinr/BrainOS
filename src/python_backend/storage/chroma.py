"""ChromaDB client + embedding function setup."""
from __future__ import annotations
import os
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from chromadb.api.types import Documents, Embeddings
from config import CHROMA_PATH, EMBEDDING_API_BASE, EMBEDDING_MODEL
from clients.vllm import VLLMClient

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


if EMBEDDING_API_BASE:
    embedding_fn = VLLMEmbeddingFunction(
        base_url=EMBEDDING_API_BASE,
        model=EMBEDDING_MODEL,
    )
    EMBEDDING_BACKEND = f"GPU · vLLM · {EMBEDDING_MODEL}"
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

# ── Bootstrap indexes from persisted brain state ───────────────────────────────
from storage.brain import _read_brain
from core.indexes import _build_indexes
_build_indexes(_read_brain())
