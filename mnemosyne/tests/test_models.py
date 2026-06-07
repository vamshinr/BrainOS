"""Model invariants — pure, no infrastructure required."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from mnemosyne.models import (
    CausalEdge,
    CausalityViolation,
    Event,
    build_causal_edge,
)


def _event(minutes: int) -> Event:
    return Event(
        summary=f"event +{minutes}m",
        occurred_at=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes),
    )


def test_confidence_must_be_in_range():
    with pytest.raises(ValueError):
        CausalEdge(
            cause_id="a", effect_id="b", confidence=1.5, evidence="x", occurred_delta_s=10
        )


def test_edge_rejects_negative_delta():
    # Pydantic wraps the validator's CausalityViolation (a ValueError) into a
    # ValidationError at direct construction; the invariant still holds.
    with pytest.raises(ValidationError) as exc:
        CausalEdge(
            cause_id="a", effect_id="b", confidence=0.9, evidence="x", occurred_delta_s=-1
        )
    assert "cause must precede effect" in str(exc.value)


def test_build_causal_edge_computes_delta():
    cause, effect = _event(0), _event(6)
    edge = build_causal_edge(cause, effect, relation="caused", confidence=0.8, evidence="x")
    assert edge.occurred_delta_s == 360
    assert edge.cause_id == cause.id and edge.effect_id == effect.id


def test_build_causal_edge_rejects_cause_after_effect():
    cause, effect = _event(10), _event(0)  # cause later than effect
    with pytest.raises(CausalityViolation):
        build_causal_edge(cause, effect, relation="caused", confidence=0.8, evidence="x")


def test_event_naive_datetime_is_normalized_to_utc():
    ev = Event(summary="x", occurred_at=datetime(2024, 1, 1, 12, 0))
    assert ev.occurred_at.tzinfo is not None
