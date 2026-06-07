"""Live end-to-end pipeline test: real Anthropic extraction + causal judgment.

Opt-in (it spends tokens): run with ``MNEMOSYNE_LLM_TESTS=1``. Proves the /ingest path
is not stubbed — events are extracted and edges judged by Haiku.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from mnemosyne.fixtures import INCIDENT_NARRATIVE, incident_query
from mnemosyne.llm import AnthropicLLM
from mnemosyne.service import MnemosyneService

pytestmark = pytest.mark.skipif(
    os.getenv("MNEMOSYNE_LLM_TESTS") != "1",
    reason="set MNEMOSYNE_LLM_TESTS=1 to run the live Anthropic pipeline test",
)


def test_full_extract_infer_retrieve(graph, vector, embedder, settings):
    if not settings.has_anthropic:
        pytest.skip("no Anthropic API key configured")

    llm = AnthropicLLM(
        settings.anthropic_api_key,
        extraction_model=settings.extraction_model,
        judgment_model=settings.judgment_model,
    )
    svc = MnemosyneService(
        graph=graph, vector=vector, embedder=embedder, settings=settings, llm=llm
    )

    ref = datetime(2024, 11, 5, 15, 0, tzinfo=timezone.utc)
    out = svc.ingest(INCIDENT_NARRATIVE, source_id="live", reference_time=ref)
    assert out["counts"]["created"] >= 4

    res = svc.retrieve(incident_query(), k=8, mode="causal")
    assert res["anchor_event_id"] is not None
    assert len(res["chain"]) >= 2
    assert isinstance(res["answer"], str) and res["answer"].strip()
