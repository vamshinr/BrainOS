"""Test fixtures. Tests run against REAL Neo4j + Qdrant (no stubs); they are isolated
on a dedicated node label (``TestEvent``) and a dedicated Qdrant collection
(``mnemosyne_test``), and skip cleanly if the services aren't reachable."""

from __future__ import annotations

import dataclasses

import pytest

from mnemosyne.config import Settings
from mnemosyne.embeddings import SentenceTransformerEmbedder
from mnemosyne.graph import Neo4jGraphStore
from mnemosyne.service import MnemosyneService
from mnemosyne.vectorstore import QdrantVectorStore

TEST_LABEL = "TestEvent"
TEST_COLLECTION = "mnemosyne_test"


def _test_settings(**overrides) -> Settings:
    base = Settings()
    return dataclasses.replace(base, qdrant_collection=TEST_COLLECTION, **overrides)


@pytest.fixture
def settings() -> Settings:
    return _test_settings()


@pytest.fixture(scope="session")
def embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(Settings().embedding_model)


@pytest.fixture
def graph(settings):
    if not settings.neo4j_password:
        pytest.skip("NEO4J_PASSWORD not set — add it to mnemosyne/.env to run live tests")
    try:
        g = Neo4jGraphStore(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            database=settings.neo4j_database,
            event_label=TEST_LABEL,
        )
        g.verify()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j unavailable: {exc}")
    g.clear()
    yield g
    g.clear()
    g.close()


@pytest.fixture
def vector(settings, embedder):
    try:
        v = QdrantVectorStore(settings.qdrant_url, TEST_COLLECTION)
        v.ensure_collection(embedder.dim)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Qdrant unavailable: {exc}")
    v.clear()
    yield v
    v.clear()


@pytest.fixture
def service(graph, vector, embedder, settings):
    # llm=None -> deterministic; the live LLM path is exercised in test_llm_pipeline.
    return MnemosyneService(
        graph=graph, vector=vector, embedder=embedder, settings=settings, llm=None
    )
