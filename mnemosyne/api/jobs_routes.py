"""HTTP surface for the async ingestion queue (mounted under /api/jobs).

  POST   /api/jobs/ingest   enqueue text -> {job_id}
  GET    /api/jobs          snapshot {active, queued, recent}
  GET    /api/jobs/stream   SSE: 'snapshot' events on change + heartbeats
  GET    /api/jobs/{id}     one job
  DELETE /api/jobs/{id}     cancel a queued job (no-op for running)
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..jobs.manager import JobManager
from .deps import get_job_manager
from .schemas import JobIngestRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/ingest")
def enqueue(req: JobIngestRequest, mgr: JobManager = Depends(get_job_manager)):
    job = mgr.enqueue(text=req.text, source_id=req.source_id, title=req.title, kind=req.kind)
    return {"job_id": job.id}


@router.get("")
def snapshot(mgr: JobManager = Depends(get_job_manager)):
    return mgr.snapshot()


@router.get("/stream")
async def stream(request: Request, mgr: JobManager = Depends(get_job_manager)):
    def frame() -> str:
        return f"data: {json.dumps({'event': 'snapshot', 'snapshot': mgr.snapshot()})}\n\n"

    async def gen():
        yield frame()
        last = mgr.version()
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            version = mgr.version()
            if version != last:
                last = version
                idle = 0
                yield frame()
            else:
                idle += 1
                if idle >= 30:  # ~15s keep-alive
                    idle = 0
                    yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{job_id}")
def get_job(job_id: str, mgr: JobManager = Depends(get_job_manager)):
    job = mgr.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job.to_public()


@router.delete("/{job_id}")
def cancel_job(job_id: str, mgr: JobManager = Depends(get_job_manager)):
    job = mgr.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job.to_public()
