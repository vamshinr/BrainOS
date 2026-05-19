"""Date parsing, temporal status inference, and temporal intent detection."""
from __future__ import annotations
import datetime
import re

def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalize_date(value: str | None) -> str | None:
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed else None


def _today_utc() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _infer_temporal_status(unit: dict, source: dict | None = None) -> str:
    today = _today_utc()
    status = str(unit.get("temporal_status") or unit.get("temporalStatus") or "").strip().lower()
    if status in _TEMPORAL_STATUSES:
        return status

    valid_from = _parse_date(unit.get("valid_from") or unit.get("validFrom"))
    valid_to = _parse_date(unit.get("valid_to") or unit.get("validTo"))
    effective = _parse_date(unit.get("effective_date") or unit.get("effectiveDate"))
    observed = _parse_date(unit.get("observed_at") or unit.get("observedAt"))

    if valid_to and valid_to < today:
        return "expired"
    if effective and effective > today:
        return "future"
    if valid_from and valid_from > today:
        return "future"
    if valid_to or valid_from or effective or observed:
        return "current"
    if source and _parse_date(source.get("capturedAt")):
        return "unknown"
    return "unknown"


def _temporal_fields(unit: dict, source: dict | None = None) -> dict:
    observed = (
        _normalize_date(unit.get("observed_at") or unit.get("observedAt"))
        or _normalize_date(source.get("capturedAt") if source else None)
    )
    fields = {
        "validFrom": _normalize_date(unit.get("valid_from") or unit.get("validFrom")),
        "validTo": _normalize_date(unit.get("valid_to") or unit.get("validTo")),
        "effectiveDate": _normalize_date(unit.get("effective_date") or unit.get("effectiveDate")),
        "observedAt": observed,
        "temporalStatus": _infer_temporal_status(unit, source),
    }
    return {k: v for k, v in fields.items() if v}


def _detect_temporal_intent(query: str) -> dict:
    q = query.lower()
    if re.search(r"\b(now|current|currently|today|latest|active)\b", q):
        return {"mode": "current", "target_date": _today_utc().isoformat()}
    if re.search(r"\b(after|from|starting|effective)\b", q):
        mode = "future"
    elif re.search(r"\b(before|previously|past|historical|history|old|q[1-4])\b", q):
        mode = "historical"
    else:
        mode = "general"

    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", q)
    target_date = date_match.group(1) if date_match else None
    if not target_date:
        month_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b",
            q,
        )
        if month_match:
            month = [
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december",
            ].index(month_match.group(1)) + 1
            target_date = datetime.date(int(month_match.group(2)), month, 1).isoformat()
    if target_date and mode == "general":
        mode = "date"
    return {"mode": mode, "target_date": target_date}


def _unit_temporal_score(unit: dict, intent: dict) -> float:
    mode = intent.get("mode", "general")
    status = unit.get("temporalStatus", "unknown")
    target_date = _parse_date(intent.get("target_date"))
    valid_from = _parse_date(unit.get("validFrom"))
    valid_to = _parse_date(unit.get("validTo"))
    effective = _parse_date(unit.get("effectiveDate"))

    if target_date:
        start = effective or valid_from
        end = valid_to
        if start and start > target_date:
            return 0.7 if mode == "future" else 0.65
        if end and end < target_date:
            return 1.15 if mode == "historical" else 0.75
        if (not start or start <= target_date) and (not end or target_date <= end):
            return 1.35

    if mode == "current":
        return {"current": 1.35, "unknown": 1.0, "future": 0.65, "historical": 0.55, "expired": 0.45}.get(status, 1.0)
    if mode == "future":
        return {"future": 1.4, "current": 1.0, "unknown": 0.9, "historical": 0.55, "expired": 0.5}.get(status, 1.0)
    if mode == "historical":
        return {"historical": 1.35, "expired": 1.25, "current": 0.9, "unknown": 0.85, "future": 0.45}.get(status, 1.0)
    return {"current": 1.1, "unknown": 1.0, "future": 0.95, "historical": 0.85, "expired": 0.75}.get(status, 1.0)


