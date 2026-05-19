"""Job handlers for text and Slack realtime ingest."""
from __future__ import annotations
import uuid
import datetime
from storage.brain import _read_brain
from core.logging import _debug_event, _utc_now_iso
from agents import ingest_agent, struct_agent

# ── Job handlers ─────────────────────────────────────────────────────────────
# Each handler takes (job, queue) and returns a result dict. The queue arg is
# used to publish step/progress updates the UI dock subscribes to.

def _handler_ingest_text(job: Job, q: JobQueue) -> dict:
    p = job.payload
    q.update_progress(job.id, step="extracting facts", progress=0.15)
    extraction = ingest_agent.extract_from_text(
        p["kind"], p["title"], p["content"], model_override=p.get("model"),
    )
    q.update_progress(job.id, step="reconciling + storing", progress=0.7)
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id, "kind": p["kind"], "title": p["title"],
        "content": p["content"], "url": p.get("url"), "capturedAt": now,
    }
    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
        relationships=extraction.get("relationships", []),
        raw_chunks=_chunk_text(p["content"], max_chars=_MAX_EXTRACTION_CHARS),
    )
    return {
        "source_id": source_id,
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
        **result,
    }


def _handler_ingest_slack_realtime(job: Job, q: JobQueue) -> dict:
    from slack_mcp.ingest import ingest_slack_document
    from slack_mcp.schemas import SlackSourceDocument

    p = job.payload
    doc = SlackSourceDocument(**p["doc"])
    q.update_progress(job.id, step="extracting Slack decision context", progress=0.15)
    result = ingest_slack_document(
        doc,
        ingest_agent=ingest_agent,
        struct_agent=struct_agent,
        chunk_text=_chunk_text,
        max_extraction_chars=_MAX_EXTRACTION_CHARS,
        utc_now_iso=_utc_now_iso,
        debug_event=_debug_event,
        model=p.get("model"),
    )

    alerts_created: list[dict] = []
    if p.get("ceo_alerts"):
        q.update_progress(job.id, step="routing CEO decision alerts", progress=0.9)
        source_id = result.get("source_id")
        brain = _read_brain()
        source = next(
            (s for s in brain.get("sources", []) if s.get("id") == source_id),
            {"id": source_id, "title": doc.title, "channelId": doc.channel_id, "channelName": doc.channel_name, "threadTs": doc.thread_ts},
        )
        units = [
            u for u in brain.get("units", [])
            if any(ev.get("sourceId") == source_id for ev in (u.get("evidence") or []) if isinstance(ev, dict))
        ]
        alerts_created = decision_alerts.create_for_source(source=source, units=units)
        _debug_event(
            "decision_alerts.created",
            "Created CEO decision alerts from realtime Slack ingest",
            source_id=source_id,
            alerts=len(alerts_created),
        )

    return {
        **result,
        "alerts_created": len(alerts_created),
        "alert_ids": [a["id"] for a in alerts_created],
    }


def _enqueue_slack_realtime_ingest(doc, ceo_alerts: bool) -> dict:
    job = job_queue.submit(
        kind="slack_realtime",
        title=doc.title,
        handler=_handler_ingest_slack_realtime,
        payload={
            "doc": doc.model_dump() if hasattr(doc, "model_dump") else doc.dict(),
            "ceo_alerts": ceo_alerts,
            "model": None,
        },
    )
    return {
        "queued": True,
        "job_id": job.id,
        "status": job.status,
        "queue_position": job_queue.queue_position(job.id),
        "title": job.title,
    }


