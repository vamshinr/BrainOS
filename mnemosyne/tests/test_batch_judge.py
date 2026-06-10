"""Batched causal judge — the pure parser, no API calls."""

from __future__ import annotations

from datetime import datetime, timezone

from mnemosyne.llm.anthropic_client import _parse_batch
from mnemosyne.models import Event

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _ev(id_: str) -> Event:
    return Event(id=id_, summary=id_, detail="", occurred_at=NOW, learned_at=NOW, tags=[])


def test_parse_batch_maps_by_cause_id_and_fills_missing_with_neutral():
    causes = [_ev("a"), _ev("b"), _ev("c")]
    out = {
        "judgments": [
            {"cause_id": "a", "relation": "caused", "confidence": 0.8, "justification": "x"},
            {"cause_id": "b", "relation": "none", "confidence": 0.1, "justification": "y"},
            # "c" omitted by the model -> must default to neutral
        ]
    }
    parsed = _parse_batch(out, causes)
    assert [p["cause_id"] for p in parsed] == ["a", "b", "c"]
    assert parsed[0]["relation"] == "caused" and parsed[0]["confidence"] == 0.8
    assert parsed[1]["relation"] == "none" and parsed[1]["confidence"] == 0.1
    assert parsed[2]["relation"] == "none" and parsed[2]["confidence"] == 0.0


def test_parse_batch_handles_garbage():
    causes = [_ev("a")]
    parsed = _parse_batch({}, causes)
    assert parsed == [
        {"cause_id": "a", "relation": "none", "confidence": 0.0, "justification": ""}
    ]


def test_parse_batch_coerces_bad_confidence_to_zero():
    causes = [_ev("a")]
    out = {"judgments": [{"cause_id": "a", "relation": "caused", "confidence": None}]}
    parsed = _parse_batch(out, causes)
    assert parsed[0]["confidence"] == 0.0
