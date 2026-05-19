"""Job queue HTTP endpoints."""
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from jobs import job_queue

router = APIRouter()

# ══════════════════════════════════════════════════════════════════════════════
# Job queue HTTP endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/jobs")
def list_jobs():
    """Return {active, queued[], recent[]}. Cheap; safe to call every few seconds
    as a fallback if SSE isn't available."""
    return job_queue.snapshot()


@router.get("/api/jobs/stream")
def stream_jobs():
    """Server-Sent Events stream of job lifecycle events. The UI dock subscribes
    via EventSource. Sends an initial snapshot, then live deltas, with a 15s
    heartbeat so reverse proxies don't time the connection out."""
    listener = job_queue.listen()

    def gen():
        try:
            yield f"data: {json.dumps({'event': 'snapshot', 'snapshot': job_queue.snapshot()})}\n\n"
            while True:
                try:
                    msg = listener.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except _stdlib_queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            job_queue.unlisten(listener)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # tell nginx not to buffer SSE
            "Connection": "keep-alive",
        },
    )


@router.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    j = job_queue.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    return j


@router.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str):
    ok = job_queue.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="job not cancelable (finished or unknown)")
    return {"ok": True, "canceled": job_id}


