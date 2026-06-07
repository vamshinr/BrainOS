"""Acceptance Test 3 — an edge where cause occurs after effect is rejected (live graph)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mnemosyne.models import CausalityViolation, Event


def _seed(service, summary: str, hour: int, minute: int) -> Event:
    ev = Event(
        summary=summary,
        occurred_at=datetime(2024, 11, 5, hour, minute, tzinfo=timezone.utc),
        tags=["x"],
    )
    ev.embedding = service.embedder.embed_one(ev.embed_text())
    service.graph.add_event(ev)
    service.vector.upsert(
        ev.id, ev.embedding, {"summary": ev.summary, "tags": ev.tags}
    )
    return ev


def test_cause_after_effect_is_rejected(service):
    early = _seed(service, "earlier event", 14, 2)
    late = _seed(service, "later event", 14, 19)

    # cause=late, effect=early would place the cause after the effect.
    with pytest.raises(CausalityViolation):
        service.add_manual_edge(late.id, early.id, relation="caused")

    # the valid direction is accepted
    edge = service.add_manual_edge(early.id, late.id, relation="caused")
    assert edge["occurred_delta_s"] == (14 * 60 + 19 - (14 * 60 + 2)) * 60
