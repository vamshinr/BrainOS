"""Ingest routes: text, file, and mock."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from core.logging import _debug_event, _utc_now_iso
from jobs import job_queue
import os
import json
from config import DATA_DIR
from storage.chroma import collection
from agents import ingest_agent, struct_agent
from jobs.handlers.text import _handler_ingest_text
from jobs.handlers.file import _handler_ingest_file

router = APIRouter()

class IngestRequest(BaseModel):
    kind: str
    title: Optional[str] = None
    content: str
    url: Optional[str] = None
    model: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None  # per-request override for the extraction call

@router.post("/api/ingest")
def ingest_text(req: IngestRequest):
    """Enqueue a text ingest job. Returns immediately with a job_id; subscribe
    to /api/jobs/stream for progress."""
    title = req.title or (req.content.strip().splitlines()[0][:80] if req.content.strip() else f"Untitled {req.kind}")
    _debug_event(
        "ingest.text.enqueue", "Queued text ingestion job",
        title=title, kind=req.kind, url=req.url, model=req.model, chars=len(req.content),
    )
    job = job_queue.submit(
        kind="ingest_text", title=title, handler=_handler_ingest_text,
        payload={"kind": req.kind, "title": title, "content": req.content,
                 "url": req.url, "model": req.model,
                 "valid_from": req.valid_from, "valid_to": req.valid_to},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }




@router.post("/api/ingest_file")
async def ingest_file(
    title: Optional[str] = Form(None),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    valid_from: Optional[str] = Form(None),
    valid_to: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Enqueue a file ingest job. We read the bytes now (so the UploadFile
    handle stays valid) then return immediately with a job_id."""
    data = await file.read()
    filename = file.filename or "upload"
    if not title:
        title = filename.rsplit(".", 1)[0] or filename
    _debug_event(
        "ingest.file.enqueue", "Queued file ingestion job",
        title=title, kind=kind, url=url, model=model,
        filename=file.filename, content_type=file.content_type, bytes=len(data),
    )
    job = job_queue.submit(
        kind="ingest_file", title=title, handler=_handler_ingest_file,
        payload={"kind": kind, "title": title, "url": url, "model": model,
                 "filename": filename, "data": data,
                 "valid_from": valid_from, "valid_to": valid_to},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


@router.post("/api/ingest_mock")
def ingest_mock():
    """Ingest mock_sources.json through the full real pipeline."""
    data_file = os.path.join(DATA_DIR, "mock_sources.json")
    if not os.path.exists(data_file):
        raise HTTPException(status_code=404, detail="Run seed_demo_data.py first.")

    with open(data_file) as f:
        items = json.load(f)

    total_units, total_entities = 0, 0
    for item in items:
        source_id = item.get("id", str(uuid.uuid4())[:8])
        item_title = item.get("title") or item.get("id", "Mock Source")
        extraction = ingest_agent.extract_from_text(
            source_type=item.get("source_type", "other"),
            title=item_title,
            content=item.get("content", ""),
        )
        source = {
            "id": source_id,
            "kind": item.get("source_type", "other"),
            "title": item_title,
            "content": item.get("content", ""),
            "capturedAt": item.get("timestamp", _utc_now_iso()),
        }
        result = struct_agent.embed_and_store(
            source_id=source_id,
            source=source,
            units=extraction.get("units", []),
            entities=extraction.get("entities", []),
            relationships=extraction.get("relationships", []),
            raw_chunks=[item.get("content", "")],  # TODO: add chunking here if needed
        )
        total_units += result["units_stored"]
        total_entities += result["entities_stored"]

    return {
        "message": "Mock data ingested through full pipeline.",
        "total_units": total_units,
        "total_entities": total_entities,
        "chroma_total": collection.count(),
    }


