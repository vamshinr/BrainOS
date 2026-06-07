"""The Section-6 acceptance scenario, as a reusable fixture.

Incident timeline (the demo):
  e1 14:02  Config change: cache TTL 3600 -> 30s
  e2 14:08  Cache hit-rate collapses
  e3 14:14  DB connection pool saturates
  e4 14:19  Checkout 500s spike            <- query target
  e5 14:41  Rollback of the config change
  e6 14:55  Recovery confirmed
  d1 3 weeks ago   Cache-warming cron (distractor, shares "cache" tags)
  d2 4 months ago  Checkout redesign doc   (distractor, shares "checkout" tags)

``seed_incident`` writes events + the known causal edges directly (deterministic, so
acceptance tests don't depend on live LLM judgment). The three-signal scorer itself is
covered by the unit tests, and the full extract->infer pipeline by the live LLM test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import Event, build_causal_edge

# A fixed base date so the fixture is fully deterministic.
BASE_DATE = datetime(2024, 11, 5, tzinfo=timezone.utc)


def _at(hh: int, mm: int) -> datetime:
    return BASE_DATE.replace(hour=hh, minute=mm)


def build_incident_events() -> dict[str, Event]:
    """Return the 8 scenario events keyed by name (e1..e6, d1, d2)."""
    e1 = Event(
        summary="Config change: cache TTL lowered from 3600s to 30s",
        detail="An engineer changed the cache TTL from 3600 seconds to 30 seconds in the service config.",
        occurred_at=_at(14, 2),
        tags=["config", "cache", "ttl"],
        source_id="incident-demo",
    )
    e2 = Event(
        summary="Cache hit-rate collapses",
        detail="The cache hit-rate collapsed because the TTL was reduced to 30s, so entries expired almost immediately.",
        occurred_at=_at(14, 8),
        tags=["cache", "hit-rate", "performance"],
        source_id="incident-demo",
    )
    e3 = Event(
        summary="DB connection pool saturates",
        detail="The database connection pool saturated as a result of the cache misses flooding the database with queries.",
        occurred_at=_at(14, 14),
        tags=["database", "connection-pool", "db"],
        source_id="incident-demo",
    )
    e4 = Event(
        summary="Checkout endpoint 500 errors spike",
        detail="Checkout started throwing HTTP 500 errors, triggered by the saturated database connection pool.",
        occurred_at=_at(14, 19),
        tags=["checkout", "http-500", "errors"],
        source_id="incident-demo",
    )
    e5 = Event(
        summary="Rollback of the cache TTL config change",
        detail="The cache TTL config change was rolled back to 3600s in response to the checkout 500 errors.",
        occurred_at=_at(14, 41),
        tags=["config", "cache", "rollback"],
        source_id="incident-demo",
    )
    e6 = Event(
        summary="Recovery confirmed",
        detail="Checkout error rates returned to normal following the rollback; recovery was confirmed.",
        occurred_at=_at(14, 55),
        tags=["recovery", "checkout", "cache"],
        source_id="incident-demo",
    )
    d1 = Event(
        summary="Cache-warming cron job scheduled",
        detail="A nightly cache-warming cron job was added to pre-populate the cache during off-peak hours.",
        occurred_at=BASE_DATE - timedelta(weeks=3),
        tags=["cache", "cron", "warming"],
        source_id="ops-wiki",
    )
    d2 = Event(
        summary="Checkout redesign design doc published",
        detail="A design document describing the upcoming checkout page redesign was published.",
        occurred_at=BASE_DATE - timedelta(days=122),
        tags=["checkout", "design", "redesign"],
        source_id="product-docs",
    )
    return {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e5": e5, "e6": e6, "d1": d1, "d2": d2}


# Edges of the known causal chain (cause_name, effect_name, relation).
_CHAIN_EDGES = [
    ("e1", "e2", "caused"),
    ("e2", "e3", "led_to"),
    ("e3", "e4", "triggered"),
    ("e4", "e5", "triggered"),
    ("e5", "e6", "led_to"),
]


def _payload(ev: Event) -> dict[str, Any]:
    return {
        "summary": ev.summary,
        "tags": ev.tags,
        "occurred_at": ev.occurred_at.isoformat(),
        "source_id": ev.source_id,
    }


def seed_incident(service, *, edge_confidence: float = 0.85) -> dict[str, Event]:
    """Seed the scenario into a service's graph + vector store. Returns the events
    keyed by name. Distractors d1/d2 are seeded with NO causal edges."""
    events = build_incident_events()

    vectors = service.embedder.embed([e.embed_text() for e in events.values()])
    for ev, vec in zip(events.values(), vectors):
        ev.embedding = vec
        service.graph.add_event(ev)
        service.vector.upsert(ev.id, vec, _payload(ev))

    for cause_name, effect_name, relation in _CHAIN_EDGES:
        edge = build_causal_edge(
            events[cause_name],
            events[effect_name],
            relation=relation,
            confidence=edge_confidence,
            evidence=f"seeded incident chain: {cause_name} {relation} {effect_name}",
            method="manual",
        )
        service.graph.add_edge(edge)

    return events


def incident_query() -> str:
    return "Why did checkout start throwing 500s?"


# A single-document narrative for exercising the full extract->infer pipeline live.
INCIDENT_NARRATIVE = """Incident timeline (all times today):
At 14:02 an engineer changed the cache TTL from 3600s to 30s in the service config.
At 14:08 the cache hit-rate collapsed because entries were expiring almost immediately.
At 14:14 the database connection pool saturated as a result of the flood of cache misses.
At 14:19 the checkout endpoint started throwing HTTP 500 errors, triggered by the saturated DB pool.
At 14:41 we rolled back the cache TTL change in response to the checkout failures.
At 14:55 checkout recovered and error rates returned to normal following the rollback.
"""
