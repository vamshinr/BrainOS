"""CEO decision alert store — persistent JSON with SSE notification support."""
from __future__ import annotations
import json
import os
import threading
import datetime
from config import DECISION_ALERTS_JSON, ALERT_MIN_CONFIDENCE, CEO_ALERT_KINDS
from core.logging import _utc_now_iso

# ── CEO decision alerts ───────────────────────────────────────────────────────
# Realtime Slack ingestion writes normal BrainOS units first. This lightweight
# store keeps the separate "executive alert" surface durable without adding a DB.
def _decision_alert_min_confidence() -> float:
    raw = os.getenv("CEO_DECISION_ALERT_MIN_CONFIDENCE", "0.78")
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 0.78


class DecisionAlertStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._listeners: list[_stdlib_queue.Queue] = []

    def _read_unlocked(self) -> list[dict]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []

    def _write_unlocked(self, alerts: list[dict]):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2)

    def list(self, *, include_closed: bool = False) -> list[dict]:
        with self._lock:
            alerts = self._read_unlocked()
        if include_closed:
            return alerts
        return [a for a in alerts if a.get("status") == "open"]

    def create_for_source(self, *, source: dict, units: list[dict]) -> list[dict]:
        min_conf = _decision_alert_min_confidence()
        now = _utc_now_iso()
        created: list[dict] = []
        with self._lock:
            alerts = self._read_unlocked()
            existing_unit_ids = {a.get("unitId") for a in alerts}
            for unit in units:
                if unit.get("id") in existing_unit_ids:
                    continue
                if unit.get("kind") != "decision":
                    continue
                if unit.get("stale") or unit.get("supersededBy"):
                    continue
                try:
                    confidence = float(unit.get("confidence", 0.0) or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < min_conf:
                    continue

                evidence = next(
                    (ev for ev in unit.get("evidence", []) if isinstance(ev, dict)),
                    {},
                )
                alert = {
                    "id": str(uuid.uuid4())[:10],
                    "unitId": unit.get("id"),
                    "statement": unit.get("statement", ""),
                    "subject": unit.get("subject", ""),
                    "confidence": confidence,
                    "sourceId": source.get("id") or evidence.get("sourceId"),
                    "sourceTitle": source.get("title", ""),
                    "channelId": source.get("channelId"),
                    "channelName": source.get("channelName"),
                    "threadTs": source.get("threadTs"),
                    "evidenceQuote": evidence.get("quote", ""),
                    "createdAt": now,
                    "status": "open",
                }
                alerts.insert(0, alert)
                created.append(alert)
            if created:
                self._write_unlocked(alerts)

        for alert in created:
            self._notify("decision_alert.created", alert)
        return created

    def update_status(self, alert_id: str, status: str) -> dict | None:
        now = _utc_now_iso()
        updated = None
        with self._lock:
            alerts = self._read_unlocked()
            for alert in alerts:
                if alert.get("id") == alert_id:
                    alert["status"] = status
                    if status == "acknowledged":
                        alert["acknowledgedAt"] = now
                    elif status == "dismissed":
                        alert["dismissedAt"] = now
                    updated = alert
                    break
            if updated:
                self._write_unlocked(alerts)
        if updated:
            self._notify(f"decision_alert.{status}", updated)
        return updated

    def listen(self) -> _stdlib_queue.Queue:
        q: _stdlib_queue.Queue = _stdlib_queue.Queue(maxsize=256)
        with self._lock:
            self._listeners.append(q)
        return q

    def unlisten(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _notify(self, event: str, alert: dict):
        payload = {"event": event, "alert": alert}
        with self._lock:
            dead = []
            for q in self._listeners:
                try:
                    q.put_nowait(payload)
                except _stdlib_queue.Full:
                    dead.append(q)
            for q in dead:
                self._listeners.remove(q)


alert_store = DecisionAlertStore(DECISION_ALERTS_JSON)
