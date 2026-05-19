"""Slack integration endpoints: resync, channels, events, canvas, slash commands."""
from __future__ import annotations
import os
import json
import time
import threading
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from storage.brain import _read_brain, _write_brain
from core.logging import _debug_event, _utc_now_iso
from core.security import _is_sensitive
from jobs import job_queue
from jobs.handlers import _enqueue_slack_realtime_ingest
from alerts.store import alert_store

router = APIRouter()

# ── Security gates ────────────────────────────────────────────────────────────
# Simple env-driven guards. If EXPORT_TOKEN is unset, export is open. If set,
# /api/skills_export and SKILLS.md downloads require a matching ?token=...
# SENSITIVE_TOPICS is a comma-separated list of substrings. /api/ask refuses
# queries that match any of them. Both are intentionally low-tech for the demo.
EXPORT_TOKEN = os.getenv("EXPORT_TOKEN", "").strip()
SENSITIVE_TOPICS = [
    t.strip().lower() for t in os.getenv("SENSITIVE_TOPICS", "").split(",") if t.strip()
]


def _is_sensitive(query: str) -> str | None:
    """Return the matched topic if the query touches a sensitive subject."""
    q = query.lower()
    for topic in SENSITIVE_TOPICS:
        if topic and topic in q:
            return topic
    return None


from integrations.slack_routes import create_slack_router
from slack_mcp.auth import load_slack_config
from slack_mcp.web_poller import (
    run_poller as _run_slack_poller,
    get_poller_status as _get_slack_poller_status,
)


@router.post("/api/slack/resync")
async def slack_resync(limit: int = 50):
    """Backfill recent Slack history into the brain. Used after a brain reset
    so the user isn't left with an empty knowledge base while waiting for the
    poller to pick up new messages.

    For each configured channel:
      1. Fetch the latest `limit` messages from conversations.history
      2. Filter out bot/self/subtype/empty messages
      3. Push each through the realtime ingest pipeline so they land in
         ChromaDB + brain.json with the same shape as polled messages
      4. Reset the poller's last_seen_ts file so future polls keep going from
         here without skipping anything

    Returns a summary of how many messages were fetched and enqueued per
    channel.
    """
    from slack_mcp.web_poller import _bot_token, _build_doc, POLLER_STATE_FILE
    token = _bot_token()
    if not token:
        raise HTTPException(status_code=400, detail="no Slack bot token configured")

    cfg = load_slack_config()
    channels = sorted(
        set(cfg.realtime_ingest_channels) | set(cfg.channel_map.keys())
    )
    # Discover the bot's own user id so we can filter its replies out.
    bot_user_id: str | None = None
    async with httpx.AsyncClient(timeout=15.0) as c:
        try:
            r = await c.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            jj = r.json()
            if jj.get("ok"):
                bot_user_id = jj.get("user_id")
        except Exception:
            pass

    summary: list[dict] = []
    newest_per_channel: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30.0) as c:
        for ch in channels:
            if not cfg.channel_allowed(ch):
                summary.append({"channel_id": ch, "skipped": "not_allowed"})
                continue
            try:
                r = await c.get(
                    "https://slack.com/api/conversations.history",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"channel": ch, "limit": max(1, min(int(limit), 200))},
                )
                j = r.json()
            except Exception as e:
                summary.append({"channel_id": ch, "error": str(e)})
                continue
            if not j.get("ok"):
                summary.append({"channel_id": ch, "error": j.get("error")})
                continue

            messages = j.get("messages") or []
            # Slack returns newest-first; reverse so the brain ingests them
            # in chronological order (and the newest ts is captured last).
            messages.reverse()
            fetched = len(messages)
            enqueued = 0
            department = cfg.department_for_channel(ch)
            ceo_alerts = ch in cfg.ceo_decision_alert_channels
            for m in messages:
                ts = str(m.get("ts") or "")
                if not ts:
                    continue
                newest_per_channel[ch] = ts
                if m.get("subtype") or m.get("bot_id"):
                    continue
                if bot_user_id and m.get("user") == bot_user_id:
                    continue
                text = str(m.get("text") or "").strip()
                if not text:
                    continue
                event_like = {
                    "type": "message",
                    "ts": ts,
                    "thread_ts": m.get("thread_ts"),
                    "user": m.get("user"),
                    "channel": ch,
                    "text": text,
                }
                doc = _build_doc(
                    event=event_like,
                    channel_id=ch,
                    channel_name=ch,
                    department=department,
                    text=text,
                )
                try:
                    _enqueue_slack_realtime_ingest(doc, ceo_alerts)
                    enqueued += 1
                except Exception as e:
                    print(f"[BrainOS] resync enqueue failed for {ch}/{ts}: {e}")
            summary.append({
                "channel_id": ch,
                "fetched": fetched,
                "enqueued": enqueued,
            })

    # Update the poller's last_seen file so it doesn't re-process the same
    # messages on its next tick.
    try:
        POLLER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = {}
        if POLLER_STATE_FILE.exists():
            try:
                existing = json.loads(POLLER_STATE_FILE.read_text()) or {}
            except Exception:
                existing = {}
        last_seen = existing.get("last_seen_ts") or {}
        last_seen.update(newest_per_channel)
        POLLER_STATE_FILE.write_text(json.dumps({"last_seen_ts": last_seen}, indent=2))
    except Exception as e:
        print(f"[BrainOS] WARNING: could not update poller state file: {e}")

    return {"ok": True, "channels": summary}


@router.get("/api/slack/channels")
async def slack_channels_info():
    """Resolve channel_id → channel_name for every configured channel via
    Slack's conversations.info. Cached for 60s to spare the rate limiter.
    UI uses this to show human-readable channel names everywhere instead of
    the bare C-prefixed IDs."""
    import time as _time
    global _channels_cache, _channels_cache_at  # type: ignore[name-defined]
    now = _time.time()
    try:
        if _channels_cache and (now - _channels_cache_at) < 60.0:
            return {"channels": _channels_cache, "cached": True}
    except NameError:
        pass

    cfg = load_slack_config()
    ids = sorted(
        set(cfg.realtime_ingest_channels)
        | set(cfg.allowed_channels)
        | set(cfg.channel_map.keys())
    )
    # Pick the bot token via the same helper the poller uses.
    from slack_mcp.web_poller import _bot_token
    token = _bot_token()
    out = []
    if token and ids:
        async with httpx.AsyncClient(timeout=10.0) as c:
            for cid in ids:
                try:
                    r = await c.get(
                        "https://slack.com/api/conversations.info",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"channel": cid},
                    )
                    j = r.json()
                    if j.get("ok"):
                        ch = j.get("channel") or {}
                        out.append({
                            "id": cid,
                            "name": ch.get("name") or cid,
                            "is_private": bool(ch.get("is_private")),
                            "topic": (ch.get("topic") or {}).get("value") or None,
                        })
                    else:
                        out.append({"id": cid, "name": cid, "error": j.get("error")})
                except Exception as e:
                    out.append({"id": cid, "name": cid, "error": str(e)})
    else:
        out = [{"id": cid, "name": cid} for cid in ids]

    _channels_cache = out  # type: ignore[name-defined]
    _channels_cache_at = now  # type: ignore[name-defined]
    return {"channels": out, "cached": False}


@router.get("/api/slack/poller/status")
def slack_poller_status():
    """Snapshot of the polling background task — tick count, last poll time,
    dispatch totals, last-seen ts per channel. Cheap; safe to poll from UI."""
    s = _get_slack_poller_status()
    # Make times human-friendly alongside the raw epoch seconds.
    import datetime as _dt
    def _fmt(ts):
        if not ts: return None
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat()
    s["started_at_iso"] = _fmt(s.get("started_at"))
    s["last_poll_at_iso"] = _fmt(s.get("last_poll_at"))
    s["last_dispatch_at_iso"] = _fmt(s.get("last_dispatch_at"))
    if s.get("last_poll_at"):
        s["seconds_since_last_poll"] = round(time.time() - s["last_poll_at"], 2)
    return s

# slack MCP router mounted via main.py


# ── Slack polling fallback ────────────────────────────────────────────────────
# Fires `conversations.history` on a fixed interval for each mapped channel
# and feeds new messages into the same realtime-ingest pipeline as the webhook.
# Use when the Slack app's Event Subscriptions URL can't be pointed at this
# backend (e.g. local dev without a tunnel, or no app collaborator access).
# The poller now waits for credentials at startup instead of bailing — so the
