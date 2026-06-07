"""Acceptance Test 4 — a near-duplicate increments reinforcement_count instead of
creating a second node (live embeddings + graph)."""

from __future__ import annotations

import dataclasses

from mnemosyne.fixtures.incident import build_incident_events
from mnemosyne.models import Event
from mnemosyne.pipeline.consolidation import find_duplicate, reinforce


def _store(service, ev: Event) -> None:
    ev.embedding = service.embedder.embed_one(ev.embed_text())
    service.graph.add_event(ev)
    service.vector.upsert(
        ev.id,
        ev.embedding,
        {"summary": ev.summary, "tags": ev.tags, "occurred_at": ev.occurred_at.isoformat()},
    )


def test_near_duplicate_reinforces_instead_of_duplicating(service, settings):
    e1 = build_incident_events()["e1"]
    _store(service, e1)
    assert service.graph.get_event(e1.id).reinforcement_count == 0

    # A near-duplicate report of the same event (different source, same time/tags).
    dup = Event(
        summary=e1.summary,
        detail=e1.detail + " This was independently confirmed by a second engineer.",
        occurred_at=e1.occurred_at,
        tags=list(e1.tags),
        source_id="second-report",
    )
    dup.embedding = service.embedder.embed_one(dup.embed_text())

    s = dataclasses.replace(settings, dedup_similarity=0.8)
    match_id = find_duplicate(dup, service.vector, service.graph, s)
    assert match_id == e1.id  # recognised as the same event, not a new node

    new_count = reinforce(match_id, service.graph, s)
    assert new_count == 1
    assert service.graph.get_event(e1.id).reinforcement_count == 1

    # only one node exists
    assert len(service.graph.all_events()) == 1
