from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .schemas import SlackSourceDocument


def ingest_slack_document(
    doc: SlackSourceDocument,
    *,
    ingest_agent: Any,
    struct_agent: Any,
    chunk_text: Callable[..., list[str]],
    max_extraction_chars: int,
    utc_now_iso: Callable[[], str],
    debug_event: Callable[..., None],
    model: str | None = None,
) -> dict[str, Any]:
    request_t0 = time.time()
    source_id = str(uuid.uuid4())[:8]
    now = utc_now_iso()
    chunks = chunk_text(doc.content, max_chars=max_extraction_chars)
    debug_event(
        "slack.ingest.start",
        "Ingesting normalized Slack content",
        source_id=source_id,
        channel_id=doc.channel_id,
        thread_ts=doc.thread_ts,
        messages=doc.message_count,
        chunks=len(chunks),
    )

    all_units: list[dict] = []
    all_entities: list[dict] = []
    all_relationships: list[dict] = []
    for idx, chunk in enumerate(chunks, start=1):
        extraction = ingest_agent.extract_from_text(
            source_type="slack",
            title=doc.title,
            content=chunk,
            model_override=model,
        )
        all_units.extend(extraction.get("units", []))
        all_entities.extend(extraction.get("entities", []))
        all_relationships.extend(extraction.get("relationships", []))
        debug_event(
            "slack.ingest.chunk.done",
            "Slack chunk extraction complete",
            source_id=source_id,
            chunk=idx,
            units=len(extraction.get("units", [])),
            entities=len(extraction.get("entities", [])),
            relationships=len(extraction.get("relationships", [])),
        )

    source = {
        "id": source_id,
        "kind": "slack",
        "title": doc.title,
        "content": doc.content[:2000],
        "url": doc.url,
        "capturedAt": now,
        "channelId": doc.channel_id,
        "channelName": doc.channel_name,
        "threadTs": doc.thread_ts,
        "department": doc.department,
        "messageCount": doc.message_count,
        "charCount": len(doc.content),
        "chunkCount": len(chunks),
    }
    result = struct_agent.embed_and_store(
        source_id=source_id,
        source=source,
        units=all_units,
        entities=all_entities,
        relationships=all_relationships,
        raw_chunks=chunks,
    )
    debug_event(
        "slack.ingest.done",
        "Slack ingestion complete",
        source_id=source_id,
        elapsed_ms=int((time.time() - request_t0) * 1000),
        units=len(all_units),
        entities=len(all_entities),
        relationships=len(all_relationships),
    )
    return {
        "source_id": source_id,
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "relationships_extracted": len(all_relationships),
        **result,
        "slack": {
            "channel_id": doc.channel_id,
            "channel_name": doc.channel_name,
            "thread_ts": doc.thread_ts,
            "message_count": doc.message_count,
            "url": doc.url,
        },
    }

