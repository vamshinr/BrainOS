"""Stage A — event extraction.

Input: raw text (a chat turn, a log block, a doc). Output: zero or more Events, each
embedded (summary + detail) and ready to be written to the graph + vector store.

Large inputs are optionally chunked (see ``pipeline.chunking``) so the extraction call
never overflows the model's context or truncates its output. Each chunk after the first
gets the tail of the previous chunk as read-only context (a sliding window) so events
that reference earlier text still resolve. Any duplicate events that slip across a
boundary are collapsed later by Stage-C consolidation (near-duplicate → reinforced, not
a second node) — the event-level analog of the design's L3 fuzzy-merge layer.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..interfaces import Embedder, LLMClient
from ..models import Event
from .chunking import chunk_text


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


def _extract_raw(
    text: str,
    reference_time: datetime,
    llm: LLMClient,
    settings: Settings,
    on_progress=None,
) -> list[dict[str, Any]]:
    """Run the LLM extraction, chunking large inputs with a sliding-context window."""
    if not settings.chunk_enabled or len(text) <= settings.chunk_max_chars:
        result = llm.extract_events(text, reference_time)
        if on_progress:
            on_progress(1.0, "Extracting events")
        return result

    chunks = chunk_text(text, size=settings.chunk_size_chars)
    n = len(chunks)
    ctx_n = max(settings.chunk_context_chars, 0)
    jobs = [
        (ch, (chunks[i - 1][-ctx_n:] if i > 0 and ctx_n else ""))
        for i, ch in enumerate(chunks)
    ]

    def run(job: tuple[str, str]) -> list[dict[str, Any]]:
        chunk, context = job
        return llm.extract_events(chunk, reference_time, context=context)

    raw: list[dict[str, Any]] = []
    done = 0

    def note(result: list[dict[str, Any]]) -> None:
        nonlocal done
        done += 1
        if result:
            raw.extend(result)
        if on_progress:
            on_progress(done / n, f"Extracting events (chunk {done}/{n})")

    workers = max(1, settings.chunk_max_concurrency)
    if workers > 1 and len(jobs) > 1:
        from concurrent.futures import as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run, job) for job in jobs]
            for future in as_completed(futures):
                note(future.result())
    else:
        for job in jobs:
            note(run(job))

    return raw


def extract_events(
    text: str,
    *,
    source_id: str,
    reference_time: datetime,
    llm: LLMClient,
    embedder: Embedder,
    settings: Settings,
    on_progress=None,
) -> list[Event]:
    raw_events = _extract_raw(text, reference_time, llm, settings, on_progress)
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
