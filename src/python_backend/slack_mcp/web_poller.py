"""
Slack Web API poller — fallback for environments where the Slack app's Events
Subscription URL can't be pointed at this backend (e.g. local dev without a
public tunnel, or a workspace where the current operator isn't a collaborator
on the Slack app and can't change its config).

Polls `conversations.history` for each mapped channel on a fixed interval,
filters out bot/self/subtype events, and feeds new messages into the same
`enqueue_realtime_ingest` pipeline that the webhook path uses — so realtime
ingest and CEO decision alerts work identically whether events arrive via
webhook push or this poll loop.

Wired into FastAPI's lifespan from main.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .auth import SLACK_DATA_DIR, SlackMCPConfig
from .schemas import SlackSourceDocument


SLACK_API_BASE = "https://slack.com/api"
POLLER_STATE_FILE = SLACK_DATA_DIR / "poller_state.json"


# Module-level runtime state, queryable via get_poller_status() so the HTTP
# layer can expose it without coupling to the asyncio task.
_RUNTIME: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "interval_s": None,
    "tick_count": 0,
    "last_poll_at": None,
    "last_dispatch_at": None,
    "dispatched_total": 0,
    "errors_total": 0,
    "channels": [],
    "bot_user_id": None,
    "last_seen_ts": {},
}


def get_poller_status() -> dict[str, Any]:
    """Snapshot of the poller's current state. Cheap to call from a route."""
    s = dict(_RUNTIME)
    s["last_seen_ts"] = dict(_RUNTIME.get("last_seen_ts") or {})
    return s


def _bot_token() -> str | None:
    """Resolve the Slack bot token (xoxb-...). Checked in priority order:
       1. SLACK_BOT_TOKEN env var (canonical name)
       2. oauth_tokens.json (written by the onboarding UI)
       3. SLACK_BOT_USER_ID env var (legacy; the .env stored the bot token
          here historically despite the misleading name)
    """
    tok = (os.getenv("SLACK_BOT_TOKEN") or "").strip()
    if tok.startswith("xoxb-"):
        return tok
    # Onboarding-written tokens
    try:
        from .auth import TOKEN_FILE
        if TOKEN_FILE.exists():
            with TOKEN_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            for key in ("bot_token", "xoxb_token"):
                val = (data.get(key) or "").strip()
                if val.startswith("xoxb-"):
                    return val
    except Exception:
        pass
    legacy = (os.getenv("SLACK_BOT_USER_ID") or "").strip()
    if legacy.startswith("xoxb-"):
        return legacy
    return None


def _load_state() -> dict[str, str]:
    try:
        with POLLER_STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return {str(k): str(v) for k, v in (data.get("last_seen_ts") or {}).items()}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _save_state(last_seen_ts: dict[str, str]) -> None:
    try:
        POLLER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with POLLER_STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump({"last_seen_ts": last_seen_ts}, f, indent=2)
    except Exception:
        pass


def _build_doc(
    *,
    event: dict[str, Any],
    channel_id: str,
    channel_name: str,
    department: str,
    text: str,
) -> SlackSourceDocument:
    """Match the shape produced by slack_routes._slack_event_document so the
    downstream pipeline can't tell whether the message came from the webhook
    or this poller."""
    ts = str(event.get("ts") or "")
    thread_ts = str(event.get("thread_ts") or ts or "")
    user = str(event.get("user") or "unknown")
    title = f"Slack Realtime: {channel_name}"
    if thread_ts:
        title = f"{title} / {thread_ts}"
    lines = [
        title,
        "",
        f"channel: {channel_name}",
        f"channel_id: {channel_id}",
        f"thread_ts: {thread_ts}",
        f"department: {department}",
        "",
        f"{user} [{ts}]",
        text,
    ]
    return SlackSourceDocument(
        title=title,
        content="\n".join(lines).strip(),
        channel_id=channel_id,
        channel_name=channel_name,
        thread_ts=thread_ts or None,
        department=department,
        message_count=1,
        raw={"event_ts": ts, "event_type": "message", "user": user, "source": "poller"},
    )


async def _resolve_bot_user_id(client: httpx.AsyncClient, token: str) -> str | None:
    try:
        r = await client.post(
            f"{SLACK_API_BASE}/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
        j = r.json()
        if j.get("ok"):
            return j.get("user_id")
    except Exception:
        return None
    return None


async def _fetch_history(
    client: httpx.AsyncClient,
    *,
    token: str,
    channel_id: str,
    oldest: str | None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"channel": channel_id, "limit": limit}
    if oldest:
        # `oldest` is inclusive of the boundary, so add a tiny epsilon to skip
        # the last seen message itself. Slack ts is a string like "1779..."
        # — bumping the microsecond suffix is the standard way.
        try:
            params["oldest"] = f"{float(oldest) + 0.000001:.6f}"
        except ValueError:
            params["oldest"] = oldest
    r = await client.get(
        f"{SLACK_API_BASE}/conversations.history",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(j.get("error") or "unknown_error")
    msgs = j.get("messages") or []
    # Slack returns newest-first; reverse so we process chronologically.
    msgs.reverse()
    return msgs


async def _poll_cycle(
    client: httpx.AsyncClient,
    *,
    token: str,
    bot_user_id: str | None,
    config: SlackMCPConfig,
    last_seen_ts: dict[str, str],
    enqueue_fn: Callable[[SlackSourceDocument, bool], dict[str, Any]],
    debug_event_fn: Callable[..., None] | None,
) -> int:
    """Poll each mapped channel once. Returns number of messages dispatched."""
    dispatched = 0
    # Poll any channel that's either in the explicit realtime list OR has a
    # department mapping (since a mapping signals intent to ingest it).
    targets = set(config.realtime_ingest_channels) | set(config.channel_map.keys())
    for channel_id in sorted(targets):
        if not config.channel_allowed(channel_id):
            continue
        oldest = last_seen_ts.get(channel_id)
        try:
            msgs = await _fetch_history(
                client, token=token, channel_id=channel_id, oldest=oldest
            )
        except Exception as e:
            if debug_event_fn:
                debug_event_fn(
                    "slack.poller.fetch_error",
                    "Failed to fetch channel history",
                    channel_id=channel_id,
                    error=str(e),
                )
            continue

        for m in msgs:
            ts = str(m.get("ts") or "")
            if not ts:
                continue
            # Bump last_seen even if we end up skipping the message — so we
            # don't see it again on the next cycle.
            last_seen_ts[channel_id] = ts

            if m.get("subtype") or m.get("bot_id"):
                continue
            if bot_user_id and m.get("user") == bot_user_id:
                continue
            text = str(m.get("text") or "").strip()
            if not text:
                continue

            department = config.department_for_channel(channel_id)
            event_like = {
                "type": "message",
                "ts": ts,
                "thread_ts": m.get("thread_ts"),
                "user": m.get("user"),
                "channel": channel_id,
                "text": text,
            }
            doc = _build_doc(
                event=event_like,
                channel_id=channel_id,
                channel_name=channel_id,  # Web API doesn't include name here
                department=department,
                text=text,
            )
            ceo_alerts = channel_id in config.ceo_decision_alert_channels
            try:
                enqueue_fn(doc, ceo_alerts)
                dispatched += 1
                if debug_event_fn:
                    debug_event_fn(
                        "slack.poller.dispatched",
                        "Dispatched polled Slack message to realtime ingest",
                        channel_id=channel_id,
                        ts=ts,
                        ceo_alerts=ceo_alerts,
                    )
            except Exception as e:
                _RUNTIME["errors_total"] = int(_RUNTIME.get("errors_total") or 0) + 1
                if debug_event_fn:
                    debug_event_fn(
                        "slack.poller.enqueue_error",
                        "Failed to enqueue polled Slack message",
                        channel_id=channel_id,
                        ts=ts,
                        error=str(e),
                    )
    if dispatched:
        _save_state(last_seen_ts)
        _RUNTIME["last_dispatch_at"] = time.time()
        _RUNTIME["dispatched_total"] = int(_RUNTIME.get("dispatched_total") or 0) + dispatched
    return dispatched


async def run_poller(
    *,
    config_loader: Callable[[], SlackMCPConfig],
    enqueue_fn: Callable[[SlackSourceDocument, bool], dict[str, Any]],
    debug_event_fn: Callable[..., None] | None = None,
    interval_s: float = 15.0,
) -> None:
    """Long-running poll loop. `config_loader` is called every cycle so the
    poller picks up credentials written by the onboarding UI without needing
    a backend restart. Cancel the asyncio task to stop.
    """
    # Wait for credentials. Re-checks every interval_s seconds; doesn't error
    # out if creds aren't there yet — that's the whole point of being
    # onboarding-friendly.
    waited_logged = False
    while True:
        token = _bot_token()
        config = config_loader()
        if token and (config.realtime_ingest_channels or config.channel_map):
            break
        if not waited_logged:
            print(
                "[BrainOS] slack web poller: waiting for credentials "
                "(complete onboarding to start polling)…"
            )
            waited_logged = True
        _RUNTIME.update({
            "running": False,
            "waiting_for_credentials": True,
            "interval_s": interval_s,
        })
        await asyncio.sleep(interval_s)
    _RUNTIME["waiting_for_credentials"] = False

    last_seen_ts = _load_state()
    async with httpx.AsyncClient(timeout=30.0) as client:
        bot_user_id = await _resolve_bot_user_id(client, token)
        channels = sorted(set(config.realtime_ingest_channels) | set(config.channel_map.keys()))
        _RUNTIME.update({
            "running": True,
            "started_at": time.time(),
            "interval_s": interval_s,
            "channels": channels,
            "bot_user_id": bot_user_id,
            "last_seen_ts": last_seen_ts,
        })
        print(
            f"[BrainOS] slack web poller: started "
            f"(interval={interval_s}s, bot_user_id={bot_user_id}, channels={channels})"
        )
        # On first run after a clean state, seed last_seen so we don't bulk-
        # replay history. Only do this for channels with no recorded ts yet.
        seeded_channels = [
            ch for ch in (set(config.realtime_ingest_channels) | set(config.channel_map.keys()))
            if ch not in last_seen_ts and config.channel_allowed(ch)
        ]
        if seeded_channels:
            for ch in seeded_channels:
                try:
                    msgs = await _fetch_history(
                        client, token=token, channel_id=ch, oldest=None, limit=1
                    )
                    if msgs:
                        last_seen_ts[ch] = str(msgs[-1].get("ts") or "")
                except Exception:
                    pass
            _save_state(last_seen_ts)

        # If verbose tick logging is on, every cycle prints "[slack-poller]
        # tick=N at HH:MM:SS dispatched_total=X". Defaults to off so the log
        # stays readable; flip with SLACK_POLLER_LOG_TICKS=true. The
        # /api/slack/poller/status endpoint is the durable observation point.
        log_ticks = os.getenv("SLACK_POLLER_LOG_TICKS", "false").strip().lower() in (
            "1", "true", "yes", "on"
        )
        while True:
            try:
                # Re-load config and re-resolve token each cycle so newly
                # onboarded channels / rotated tokens are picked up live.
                fresh_token = _bot_token() or token
                fresh_config = config_loader()
                fresh_channels = sorted(
                    set(fresh_config.realtime_ingest_channels)
                    | set(fresh_config.channel_map.keys())
                )
                if fresh_channels != _RUNTIME.get("channels"):
                    _RUNTIME["channels"] = fresh_channels
                if fresh_token != token:
                    token = fresh_token
                    bot_user_id = await _resolve_bot_user_id(client, token)
                    _RUNTIME["bot_user_id"] = bot_user_id
                config = fresh_config

                await _poll_cycle(
                    client,
                    token=token,
                    bot_user_id=bot_user_id,
                    config=config,
                    last_seen_ts=last_seen_ts,
                    enqueue_fn=enqueue_fn,
                    debug_event_fn=debug_event_fn,
                )
                _RUNTIME["tick_count"] = int(_RUNTIME.get("tick_count") or 0) + 1
                _RUNTIME["last_poll_at"] = time.time()
                _RUNTIME["last_seen_ts"] = last_seen_ts
                if log_ticks:
                    print(
                        f"[slack-poller] tick={_RUNTIME['tick_count']} "
                        f"at {time.strftime('%H:%M:%S')} "
                        f"dispatched_total={_RUNTIME['dispatched_total']}"
                    )
            except Exception as e:
                _RUNTIME["errors_total"] = int(_RUNTIME.get("errors_total") or 0) + 1
                print(f"[BrainOS] slack web poller cycle error: {e}")
            await asyncio.sleep(interval_s)
