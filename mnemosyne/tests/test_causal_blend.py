"""Three-signal blending + pruning behaviour of score_pair / infer_edges (no LLM)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mnemosyne.config import Settings
from mnemosyne.models import Event
from mnemosyne.pipeline.causal import blend, infer_edges, score_pair

_S = Settings()
_BASE = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def _ev(minutes: int, summary="x", detail="", tags=None) -> Event:
    return Event(
        summary=summary,
        detail=detail,
        occurred_at=_BASE + timedelta(minutes=minutes),
        tags=tags or [],
    )


def test_blend_weights():
    # default weights 0.3/0.2/0.5
    assert abs(blend(1.0, 1.0, 1.0, _S) - 1.0) < 1e-9
    assert abs(blend(1.0, 0.0, 0.0, _S) - 0.3) < 1e-9


def test_score_pair_prunes_when_cause_after_effect():
    assert score_pair(_ev(10), _ev(0), settings=_S, llm=None) is None


def test_score_pair_without_llm_is_renormalized_and_valid():
    cause = _ev(0, "ttl change", tags=["cache"])
    effect = _ev(5, "hit-rate fell", "collapsed because the ttl dropped", tags=["cache"])
    edge = score_pair(cause, effect, settings=_S, llm=None)
    assert edge is not None
    assert 0.0 < edge.confidence <= 1.0
    assert edge.method == "temporal+linguistic"
    assert edge.occurred_delta_s == 300


def test_infer_edges_skips_pruned_candidates():
    effect = _ev(5, "effect")
    candidates = [_ev(0, "valid cause"), _ev(10, "future, invalid")]
    edges = infer_edges(effect, candidates, settings=_S, llm=None)
    # only the candidate that precedes the effect survives
    assert len(edges) == 1
    assert edges[0].cause_id == candidates[0].id
