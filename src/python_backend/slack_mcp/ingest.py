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
    utc_now_iso: Callable[[], str],
    debug_event: Callable[..., None],
    model: str | None = None,
) -> dict[str, Any]:
    request_t0 = time.time()
    source_id = str(uuid.uuid4())[:8]
    now = utc_now_iso()
    debug_event(
        "slack.ingest.start",
        "Ingesting normalized Slack content",
        source_id=source_id,
        channel_id=doc.channel_id,
        thread_ts=doc.thread_ts,
        messages=doc.message_count,
        chars=len(doc.content),
    )

    # TODO: add chunking here if Slack threads regularly exceed model context limits
    extraction = ingest_agent.extract_from_text(
        source_type="slack",
        title=doc.title,
        content=doc.content,
        model_override=model,
    )
    all_units: list[dict] = extraction.get("units", [])
    all_entities: list[dict] = extraction.get("entities", [])
    all_relationships: list[dict] = extraction.get("relationships", [])

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
    }
    result = struct_agent.embed_and_store(
        source_id=source_id,
        source=source,
        units=all_units,
        entities=all_entities,
        relationships=all_relationships,
        raw_chunks=[doc.content],  # TODO: split into chunks here if needed
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

