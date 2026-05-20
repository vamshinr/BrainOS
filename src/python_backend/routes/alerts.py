"""Decision alert endpoints (list, SSE stream, ack, dismiss)."""
from __future__ import annotations
import json
import queue as _stdlib_queue
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from alerts.store import alert_store
from config import ALERT_MIN_CONFIDENCE

router = APIRouter()


@router.get("/api/decision-alerts")
def list_decision_alerts(include_closed: bool = False):
    return {
        "alerts": alert_store.list(include_closed=include_closed),
        "min_confidence": ALERT_MIN_CONFIDENCE,
    }


@router.get("/api/decision-alerts/stream")
def stream_decision_alerts():
    listener = alert_store.listen()

    def gen():
        try:
            yield f"data: {json.dumps({'event': 'snapshot', 'alerts': alert_store.list()})}\n\n"
            while True:
                try:
                    msg = listener.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except _stdlib_queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            alert_store.unlisten(listener)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/api/decision-alerts/{alert_id}/ack")
def acknowledge_decision_alert(alert_id: str):
    alert = alert_store.update_status(alert_id, "acknowledged")
    if not alert:
        raise HTTPException(status_code=404, detail="decision alert not found")
    return {"ok": True, "alert": alert}


@router.post("/api/decision-alerts/{alert_id}/dismiss")
def dismiss_decision_alert(alert_id: str):
    alert = alert_store.update_status(alert_id, "dismissed")
    if not alert:
        raise HTTPException(status_code=404, detail="decision alert not found")
    return {"ok": True, "alert": alert}


