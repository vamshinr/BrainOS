"""Signal 2 — linguistic / co-occurrence cues, in isolation."""

from __future__ import annotations

from datetime import datetime, timezone

from mnemosyne.models import Event
from mnemosyne.pipeline.causal import linguistic_score

_T = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def _ev(summary: str, detail: str, tags: list[str]) -> Event:
    return Event(summary=summary, detail=detail, occurred_at=_T, tags=tags)


def test_causal_marker_is_detected():
    cause = _ev("ttl lowered", "", ["cache"])
    effect = _ev("hit-rate fell", "hit-rate collapsed because the ttl dropped", ["cache"])
    score, markers = linguistic_score(cause, effect)
    assert "because" in markers
    assert score > 0.5


def test_no_marker_no_overlap_is_low():
    cause = _ev("unrelated a", "nothing here", ["alpha"])
    effect = _ev("unrelated b", "also nothing", ["omega"])
    score, markers = linguistic_score(cause, effect)
    assert markers == []
    assert score == 0.0


def test_tag_overlap_raises_score_without_marker():
    cause = _ev("a", "plain text", ["cache", "ttl"])
    effect = _ev("b", "plain text", ["cache", "ttl"])
    score, markers = linguistic_score(cause, effect)
    assert markers == []
    assert score > 0.0
