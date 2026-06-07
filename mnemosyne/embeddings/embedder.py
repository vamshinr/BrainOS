"""Sentence-transformers embeddings (all-MiniLM-L6-v2 by default, 384-dim).

The model is loaded lazily on first use so importing the package stays cheap. Vectors
are L2-normalized, so cosine similarity equals dot product.
"""

from __future__ import annotations

from typing import Optional


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None  # lazy
        self._dim: Optional[int] = None

    def _ensure(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dim(self) -> int:
        self._ensure()
        assert self._dim is not None
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure()
        vectors = model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return [v.tolist() for v in vectors]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
