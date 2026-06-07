"""Stage C — consolidation (cross-session reinforcement) + temporal decay.

When a new event closely matches an existing one (high embedding similarity + tag
overlap + compatible time), we don't duplicate it. Instead we increment its
``reinforcement_count`` and bump confidence on its edges: repeated independent
confirmation = higher-trust memory.

``salience`` decays with age unless reinforced, and is used to break ties at retrieval.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from ..config import Settings
from ..interfaces import GraphStore, VectorStore
from ..models import Event

# How much each independent confirmation strengthens an event's edges.
_EDGE_BUMP = 0.05


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = {t.lower() for t in a}, {t.lower() for t in b}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def salience(event: Event, now: datetime, half_life_s: float) -> float:
    """Recency-decayed, reinforcement-boosted salience score."""
    age = max((now - event.occurred_at).total_seconds(), 0.0)
    decay = 0.5 ** (age / half_life_s) if half_life_s > 0 else 1.0
    boost = 1.0 + math.log1p(max(event.reinforcement_count, 0))
    return decay * boost


def _time_compatible(a: Event, b: Event, window_s: float) -> bool:
    return abs((a.occurred_at - b.occurred_at).total_seconds()) <= window_s


def find_duplicate(
    event: Event, vector: VectorStore, graph: GraphStore, settings: Settings
) -> Optional[str]:
    """Return the id of an existing near-duplicate event, or None."""
    if event.embedding is None:
        return None
    for eid, score, _payload in vector.search(event.embedding, k=5):
        if eid == event.id or score < settings.dedup_similarity:
            continue
        existing = graph.get_event(eid)
        if existing is None:
            continue
        if _jaccard(existing.tags, event.tags) >= 0.3 and _time_compatible(
            existing, event, settings.dedup_time_window_s
        ):
            return eid
    return None


def reinforce(
    event_id: str, graph: GraphStore, settings: Settings, *, now: Optional[datetime] = None
) -> int:
    """Reinforce an existing event: bump reinforcement_count, strengthen its edges,
    and refresh its stored salience. Returns the new reinforcement_count."""
    now = now or datetime.now(timezone.utc)
    count = graph.increment_reinforcement(event_id, 1)
    graph.bump_edge_confidence(event_id, _EDGE_BUMP, cap=1.0)
    existing = graph.get_event(event_id)
    if existing is not None:
        graph.update_salience(event_id, salience(existing, now, settings.salience_half_life_s))
    return count
