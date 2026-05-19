"""Decision alert endpoints (list, SSE stream, ack, dismiss)."""
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from alerts.store import alert_store

router = APIRouter()

# ══════════════════════════════════════════════════════════════════════════════
# CEO decision alert endpoints
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/decision-alerts")
def list_decision_alerts(include_closed: bool = False):
    return {
        "alerts": decision_alerts.list(include_closed=include_closed),
        "min_confidence": _decision_alert_min_confidence(),
    }


@router.get("/api/decision-alerts/stream")
def stream_decision_alerts():
    listener = decision_alerts.listen()

    def gen():
        try:
            yield f"data: {json.dumps({'event': 'snapshot', 'alerts': decision_alerts.list()})}\n\n"
            while True:
                try:
                    msg = listener.get(timeout=15)
                    yield f"data: {json.dumps(msg)}\n\n"
                except _stdlib_queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            decision_alerts.unlisten(listener)

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
    alert = decision_alerts.update_status(alert_id, "acknowledged")
    if not alert:
        raise HTTPException(status_code=404, detail="decision alert not found")
    return {"ok": True, "alert": alert}


@router.post("/api/decision-alerts/{alert_id}/dismiss")
def dismiss_decision_alert(alert_id: str):
    alert = decision_alerts.update_status(alert_id, "dismissed")
    if not alert:
        raise HTTPException(status_code=404, detail="decision alert not found")
    return {"ok": True, "alert": alert}


