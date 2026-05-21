"""Slack ID enrichment — turn raw Slack IDs into human-readable content.

Both ingest paths (the webhook events route in integrations/slack_routes.py
and the polling fallback in slack_mcp/web_poller.py) feed messages into the
same queue, so they share this module to:
  • resolve channel IDs (C0B2ALQLA4F) → names (#all-brainos)
  • resolve user IDs (U0B2LN61ZOB) → display names (the message sender)
  • convert Slack ts epoch floats → ISO 8601 timestamps

so the brain captures *who* said something and *when* — making temporal
questions like "what did people ask about recently?" answerable.
"""
from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from typing import Optional

import httpx

from .schemas import SlackSourceDocument

SLACK_API_BASE = "https://slack.com/api"

# Process-lifetime caches. Channel/user names change rarely, so resolving each
# ID once keeps us well under Slack's conversations.info / users.info rate
# limits even with the poller running every 15s. Only successful lookups are
# cached, so a transient API failure is retried on the next message.
_CHANNEL_NAME_CACHE: dict[str, str] = {}
_USER_NAME_CACHE: dict[str, str] = {}


def slack_ts_to_iso(ts: str | None) -> Optional[str]:
    """Convert a Slack message ts ('1779348833.073879') to an ISO 8601 UTC
    string. Returns None when ts is missing or unparseable."""
    if not ts:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            float(ts), tz=datetime.timezone.utc
        ).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


@asynccontextmanager
async def _ensure_client(client: httpx.AsyncClient | None):
    """Yield the caller's client if it gave one (the poller reuses a single
    client), otherwise spin up a short-lived one (the webhook path)."""
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=10.0) as c:
            yield c


async def resolve_channel_name(
    channel_id: str | None,
    token: str | None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Resolve a Slack channel ID to its name (no leading '#'). Falls back to
    the raw ID on any failure. Cached for the process lifetime."""
    if not channel_id:
        return channel_id or ""
    if channel_id in _CHANNEL_NAME_CACHE:
        return _CHANNEL_NAME_CACHE[channel_id]
    name = channel_id
    if token:
        try:
            async with _ensure_client(client) as c:
                r = await c.get(
                    f"{SLACK_API_BASE}/conversations.info",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"channel": channel_id},
                )
            j = r.json()
            if j.get("ok"):
                name = (j.get("channel") or {}).get("name") or channel_id
        except Exception:
            name = channel_id
    if name != channel_id:
        _CHANNEL_NAME_CACHE[channel_id] = name
    return name


async def resolve_user_name(
    user_id: str | None,
    token: str | None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Resolve a Slack user ID to a display name. Falls back to the raw ID on
    any failure. Cached for the process lifetime."""
    if not user_id or user_id == "unknown":
        return user_id or "unknown"
    if user_id in _USER_NAME_CACHE:
        return _USER_NAME_CACHE[user_id]
    name = user_id
    if token:
        try:
            async with _ensure_client(client) as c:
                r = await c.get(
                    f"{SLACK_API_BASE}/users.info",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"user": user_id},
                )
            j = r.json()
            if j.get("ok"):
                u = j.get("user") or {}
                prof = u.get("profile") or {}
                name = (
                    prof.get("display_name")
                    or prof.get("real_name")
                    or u.get("real_name")
                    or u.get("name")
                    or user_id
                )
        except Exception:
            name = user_id
    if name != user_id:
        _USER_NAME_CACHE[user_id] = name
    return name


def build_slack_document(
    *,
    channel_id: str,
    channel_name: str,
    user_id: str,
    user_name: str,
    ts: str,
    thread_ts: str | None,
    department: str,
    text: str,
) -> SlackSourceDocument:
    """Build the SlackSourceDocument both ingest paths feed into the queue.

    `channel_name` and `user_name` should already be resolved to human names.
    Keeps the same content shape the frontend's extractSlackText() expects:
    three blank-line-separated blocks, message text after the sender header.
    """
    message_at = slack_ts_to_iso(ts)
    channel_label = f"#{channel_name}" if channel_name else (channel_id or "unknown")
    sender = user_name or user_id or "unknown"
    when = message_at or str(ts or "unknown time")
    title = f"Slack Realtime: {channel_label}"
    lines = [
        title,
        "",
        f"channel: {channel_label}",
        f"channel_id: {channel_id}",
        f"thread_ts: {thread_ts or ''}",
        f"department: {department}",
        "",
        f"{sender} [{when}]",
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
        user_id=user_id,
        user_name=user_name,
        message_ts=str(ts or ""),
        message_at=message_at,
        raw={
            "event_ts": str(ts or ""),
            "event_type": "message",
            "user": user_id,
            "user_name": user_name,
        },
    )
