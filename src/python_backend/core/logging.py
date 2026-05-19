"""In-memory call log and structured debug events."""
from __future__ import annotations
import collections
import threading
import datetime

# ── Recent-calls log (in-memory ring buffer, surfaced to the dashboard) ──────
_call_log: collections.deque = collections.deque(maxlen=80)
_call_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _debug_value(value) -> str:
    if isinstance(value, str):
        value = value.replace("\n", "\\n")
        if len(value) > 140:
            value = value[:137] + "..."
    return str(value)


def _debug_event(stage: str, message: str, **fields):
    details = " | ".join(
        f"{key}={_debug_value(value)}" for key, value in fields.items()
        if value is not None
    )
    suffix = f" | {details}" if details else ""
    print(f"[BrainOS][{_utc_now_iso()}][{stage}] {message}{suffix}")


def _log_call(
    task: str,
    model: str,
    latency_ms: int,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    ok: bool = True,
    note: str = "",
):
    with _call_lock:
        _call_log.append({
            "ts": _utc_now_iso(),
            "task": task,
            "model": model,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "ok": ok,
            "note": note,
        })


