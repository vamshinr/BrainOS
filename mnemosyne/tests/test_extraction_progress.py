import dataclasses
from datetime import datetime, timezone

from mnemosyne.config import Settings
from mnemosyne.pipeline.extraction import extract_events


class FakeEmbedder:
    dim = 384

    def embed(self, texts):
        return [[0.0] * self.dim for _ in texts]

    def embed_one(self, text):
        return [0.0] * self.dim


class FakeLLM:
    def extract_events(self, text, reference_time, context=""):
        return [{"summary": f"event:{text[:8]}", "occurred_at": None, "tags": []}]

    def judge_causality_batch(self, effect, causes):
        return [
            {"cause_id": c.id, "relation": "none", "confidence": 0.0, "justification": ""}
            for c in causes
        ]

    def synthesize(self, query, ordered_chain):
        return ""


def test_chunk_progress_is_reported_monotonically():
    settings = dataclasses.replace(
        Settings(),
        chunk_enabled=True,
        chunk_max_chars=10,
        chunk_size_chars=20,
        chunk_context_chars=0,
        chunk_max_concurrency=1,
    )
    calls: list[tuple[float, str]] = []
    extract_events(
        "A" * 60,
        source_id="x",
        reference_time=datetime.now(timezone.utc),
        llm=FakeLLM(),
        embedder=FakeEmbedder(),
        settings=settings,
        on_progress=lambda f, step: calls.append((f, step)),
    )
    assert calls, "expected at least one progress callback"
    fractions = [f for f, _ in calls]
    assert fractions == sorted(fractions)        # monotonic non-decreasing
    assert fractions[-1] == 1.0
    assert "chunk" in calls[-1][1].lower()


def test_no_callback_is_safe():
    # Small text, no chunking, no on_progress — must not raise.
    extract_events(
        "tiny",
        source_id="x",
        reference_time=datetime.now(timezone.utc),
        llm=FakeLLM(),
        embedder=FakeEmbedder(),
        settings=Settings(),
    )
