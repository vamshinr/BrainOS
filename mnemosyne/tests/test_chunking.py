"""Chunking: boundary-aware splitting, full coverage, and the sliding-context window.

Pure tests — no Neo4j/Qdrant/LLM. A tiny capturing fake stands in for the LLM to assert
the extraction orchestration (how many calls, what context) without a network round-trip.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from mnemosyne.config import Settings
from mnemosyne.pipeline.chunking import chunk_text
from mnemosyne.pipeline.extraction import extract_events

_REF = datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_small_text_is_one_chunk():
    assert chunk_text("hello world.", size=1000) == ["hello world."]
    assert chunk_text("", size=1000) == []


def test_large_text_splits_and_covers_everything():
    sentences = [f"Sentence number {i} concerns subject {i}." for i in range(200)]
    text = " ".join(sentences)
    chunks = chunk_text(text, size=500)

    assert len(chunks) > 1
    # size budget respected (a little slack for boundary snapping)
    assert all(len(c) <= 500 + 50 for c in chunks)
    # nothing dropped: every sentence shows up in some chunk
    joined = " ".join(chunks)
    for s in sentences:
        assert s in joined


class _FakeEmbedder:
    dim = 384

    def embed(self, texts):
        return [[0.0] * 384 for _ in texts]

    def embed_one(self, text):
        return [0.0] * 384


class _CapturingLLM:
    """Records each extract_events call instead of calling Anthropic."""

    def __init__(self):
        self.calls: list[dict] = []

    def extract_events(self, text, reference_time, context=""):
        self.calls.append({"text": text, "context": context})
        return []

    def judge_causality(self, cause, effect):
        return {"relation": "none", "confidence": 0.0, "justification": ""}

    def synthesize(self, query, chain):
        return ""


def _long_text() -> str:
    return " ".join(f"Event {i} happened at minute {i}." for i in range(300))


def test_chunked_extraction_passes_sliding_context():
    s = dataclasses.replace(
        Settings(),
        chunk_enabled=True,
        chunk_max_chars=400,
        chunk_size_chars=300,
        chunk_context_chars=60,
        chunk_max_concurrency=1,
    )
    llm = _CapturingLLM()
    extract_events(_long_text(), source_id="t", reference_time=_REF, llm=llm, embedder=_FakeEmbedder(), settings=s)

    assert len(llm.calls) > 1                        # the text was chunked
    assert llm.calls[0]["context"] == ""             # first chunk: no preceding context
    assert all(c["context"] for c in llm.calls[1:])  # later chunks: sliding context present
    assert all(len(c["text"]) <= 300 + 50 for c in llm.calls)


def test_chunking_disabled_makes_one_call():
    s = dataclasses.replace(Settings(), chunk_enabled=False)
    llm = _CapturingLLM()
    extract_events(_long_text(), source_id="t", reference_time=_REF, llm=llm, embedder=_FakeEmbedder(), settings=s)
    assert len(llm.calls) == 1                        # whole text in a single call


def test_small_text_below_threshold_makes_one_call():
    s = dataclasses.replace(Settings(), chunk_enabled=True, chunk_max_chars=100000)
    llm = _CapturingLLM()
    extract_events("A short note.", source_id="t", reference_time=_REF, llm=llm, embedder=_FakeEmbedder(), settings=s)
    assert len(llm.calls) == 1
