from __future__ import annotations

import datetime
from typing import Any

from .schemas import SlackMessage, SlackSourceDocument


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _ts_to_iso(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        seconds = float(ts)
        return datetime.datetime.fromtimestamp(seconds, datetime.UTC).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _extract_messages(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("messages", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    content = payload.get("content")
    if isinstance(content, list):
        out: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("json"), dict):
                out.append(item["json"])
            elif isinstance(item, dict):
                out.append(item)
        return out
    return []


def normalize_messages(payload: Any) -> list[SlackMessage]:
    messages: list[SlackMessage] = []
    for raw in _extract_messages(payload):
        user = _pick(raw, "user_name", "username", "display_name", "real_name", "user", "user_id") or "unknown"
        text = _pick(raw, "text", "message", "content", "body") or ""
        ts = str(_pick(raw, "ts", "timestamp", "message_ts", "created_at") or "")
        messages.append(SlackMessage(
            user=str(user),
            text=str(text),
            ts=ts,
            datetime=str(_pick(raw, "datetime", "created_at") or _ts_to_iso(ts) or ts),
            permalink=_pick(raw, "permalink", "url"),
            raw=raw,
        ))
    return messages


def build_source_document(
    payload: Any,
    *,
    channel_id: str | None,
    channel_name: str | None = None,
    thread_ts: str | None = None,
    department: str = "general",
    title_prefix: str = "Slack Thread",
) -> SlackSourceDocument:
    messages = normalize_messages(payload)
    display_channel = channel_name or channel_id or "unknown-channel"
    title = f"{title_prefix}: {display_channel}"
    if thread_ts:
        title = f"{title} / {thread_ts}"

    lines = [
        title,
        "",
        f"channel: {display_channel}",
        f"channel_id: {channel_id or ''}",
        f"thread_ts: {thread_ts or ''}",
        f"department: {department}",
        "",
    ]
    for msg in messages:
        timestamp = msg.datetime or msg.ts
        lines.append(f"{msg.user} [{timestamp}]")
        lines.append(msg.text)
        lines.append("")

    url = next((msg.permalink for msg in messages if msg.permalink), None)
    return SlackSourceDocument(
        title=title,
        content="\n".join(lines).strip(),
        channel_id=channel_id,
        channel_name=channel_name,
        thread_ts=thread_ts,
        department=department,
        url=url,
        message_count=len(messages),
        raw={"payload_type": type(payload).__name__},
    )

