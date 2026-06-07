"""Stage A — event extraction.

Input: raw text (a chat turn, a log block, a doc). Output: zero or more Events, each
embedded (summary + detail) and ready to be written to the graph + vector store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..interfaces import Embedder, LLMClient
from ..models import Event


def _parse_dt(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return fallback
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback


def extract_events(
    text: str,
    *,
    source_id: str,
    reference_time: datetime,
    llm: LLMClient,
    embedder: Embedder,
) -> list[Event]:
    raw_events = llm.extract_events(text, reference_time)
    learned_at = datetime.now(timezone.utc)

    events: list[Event] = []
    for item in raw_events:
        summary = (item.get("summary") or "").strip()
        if not summary:
            continue
        occurred_at = _parse_dt(item.get("occurred_at"), reference_time)
        tags = [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()]
        events.append(
            Event(
                summary=summary,
                detail=(item.get("detail") or "").strip(),
                occurred_at=occurred_at,
                learned_at=learned_at,
                tags=tags,
                source_id=source_id,
            )
        )

    # Embed summary+detail for the anchor step.
    if events:
        vectors = embedder.embed([e.embed_text() for e in events])
        for event, vector in zip(events, vectors):
            event.embedding = vector

    # Process earliest-first so causes are stored before their effects.
    events.sort(key=lambda e: e.occurred_at)
    return events
