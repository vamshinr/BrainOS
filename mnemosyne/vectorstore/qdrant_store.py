"""Qdrant-backed vector store for the semantic anchor step.

Adapts to whatever the target collection looks like: if it already exists with a
*named* dense vector (as the pre-provisioned ``mnemosyne_vectors`` collection does),
we detect and use that name; otherwise we create a simple single-vector collection.
Sparse vectors, if configured on the collection, are left untouched.
"""

from __future__ import annotations

from typing import Any, Optional

from qdrant_client import QdrantClient, models


class QdrantVectorStore:
    def __init__(self, url: str, collection: str) -> None:
        self._client = QdrantClient(url=url)
        self._collection = collection
        self._vector_name: Optional[str] = None  # set by ensure_collection

    def ensure_collection(self, dim: int) -> None:
        if self._client.collection_exists(self._collection):
            self._vector_name = self._detect_vector_name()
            return
        # Create a minimal single (unnamed) dense-vector collection.
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        self._vector_name = None

    def _detect_vector_name(self) -> Optional[str]:
        info = self._client.get_collection(self._collection)
        vectors = info.config.params.vectors
        # dict -> named vectors; VectorParams -> single unnamed vector
        if isinstance(vectors, dict):
            if "dense" in vectors:
                return "dense"
            return next(iter(vectors.keys()), None)
        return None

    def _vec(self, vector: list[float]):
        return {self._vector_name: vector} if self._vector_name else vector

    def upsert(self, event_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(id=event_id, vector=self._vec(vector), payload=payload)
            ],
        )

    def search(self, vector: list[float], k: int) -> list[tuple[str, float, dict[str, Any]]]:
        query_vector: Any = (self._vector_name, vector) if self._vector_name else vector
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            limit=k,
            with_payload=True,
        )
        return [(str(h.id), float(h.score), dict(h.payload or {})) for h in hits]

    def delete(self, event_id: str) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=[event_id]),
        )

    def count(self) -> int:
        return int(self._client.count(self._collection, exact=True).count)

    def clear(self) -> None:
        # Delete all points, keep the collection + schema intact.
        self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(filter=models.Filter()),
        )

    def clear_all(self) -> None:
        # Blanket wipe: delete all points from EVERY collection (schemas kept intact).
        for c in self._client.get_collections().collections:
            self._client.delete(
                collection_name=c.name,
                points_selector=models.FilterSelector(filter=models.Filter()),
            )
