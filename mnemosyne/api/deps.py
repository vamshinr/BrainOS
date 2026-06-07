"""Singleton wiring of the real backends into a MnemosyneService.

Construction is lazy (first request) so the process can start even before Neo4j is
reachable; ``/health`` then reports the degraded state instead of crashing.
"""

from __future__ import annotations

from typing import Optional

from ..config import get_settings
from ..embeddings import SentenceTransformerEmbedder
from ..graph import Neo4jGraphStore
from ..llm import AnthropicLLM
from ..service import MnemosyneService
from ..vectorstore import QdrantVectorStore

_service: Optional[MnemosyneService] = None


def build_service() -> MnemosyneService:
    s = get_settings()
    graph = Neo4jGraphStore(
        s.neo4j_uri,
        s.neo4j_user,
        s.neo4j_password,
        database=s.neo4j_database,
        event_label=s.neo4j_event_label,
    )
    vector = QdrantVectorStore(s.qdrant_url, s.qdrant_collection)
    embedder = SentenceTransformerEmbedder(s.embedding_model)
    llm = (
        AnthropicLLM(
            s.anthropic_api_key,
            extraction_model=s.extraction_model,
            judgment_model=s.judgment_model,
            extraction_max_tokens=s.extraction_max_tokens,
        )
        if s.has_anthropic
        else None
    )
    return MnemosyneService(graph=graph, vector=vector, embedder=embedder, settings=s, llm=llm)


def get_service() -> MnemosyneService:
    global _service
    if _service is None:
        _service = build_service()
    return _service


def reset_service() -> None:
    global _service
    if _service is not None:
        try:
            _service.close()
        except Exception:  # noqa: BLE001
            pass
    _service = None
