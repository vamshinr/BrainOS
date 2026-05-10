"""Slack poll-based connector. Reads channels via bot token, ingests threads as sources."""
from __future__ import annotations

import json
import os
import threading
import time
import datetime
import uuid
import collections
from pathlib import Path
from typing import Callable, Optional

import httpx

SLACK_API = "https://slack.com/api"
CONFIG_PATH = Path(__file__).parent / "slack_config.json"
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_POLL_SECONDS = 300

_lock = threading.Lock()
_poll_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_last_sync_status: dict = {"running": False, "last_run_at": None, "last_error": None, "ingested": 0}


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "bot_token": os.getenv("SLACK_BOT_TOKEN", ""),
            "team": None,
            "channels": [],          # selected channel ids
            "cursors": {},           # channel_id → last oldest_ts ingested
            "lookback_days": DEFAULT_LOOKBACK_DAYS,
            "poll_seconds": DEFAULT_POLL_SECONDS,
        }
    return json.loads(CONFIG_PATH.read_text())


def _save_config(cfg: dict) -> None:
    with _lock:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=SLACK_API,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def _slack_get(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    """Single request with rate-limit retry."""
    for attempt in range(3):
        r = client.get(path, params=params or {})
        if r.status_code == 429:
            retry_after = int(r.headers.get("Retry-After", "2"))
            time.sleep(retry_after)
            continue
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API {path} failed: {data.get('error')}")
        return data
    raise RuntimeError(f"Slack API {path} rate-limited after retries")


# ── Public API ────────────────────────────────────────────────────────────────

def validate_token(token: str) -> dict:
    """Calls auth.test. Returns {team, team_id, user, user_id, bot_id}."""
    with _client(token) as c:
        data = _slack_get(c, "/auth.test")
    return {
        "team": data.get("team"),
        "team_id": data.get("team_id"),
        "user": data.get("user"),
        "user_id": data.get("user_id"),
        "bot_id": data.get("bot_id"),
    }


def connect(token: str) -> dict:
    info = validate_token(token)
    cfg = _load_config()
    cfg["bot_token"] = token
    cfg["team"] = info["team"]
    _save_config(cfg)
    return info


def list_channels(token: Optional[str] = None) -> list[dict]:
    cfg = _load_config()
    tok = token or cfg.get("bot_token")
    if not tok:
        raise RuntimeError("No Slack token configured")
    out: list[dict] = []
    cursor = ""
    with _client(tok) as c:
        while True:
            params = {
                "types": "public_channel,private_channel",
                "limit": 200,
                "exclude_archived": "true",
            }
            if cursor:
                params["cursor"] = cursor
            data = _slack_get(c, "/conversations.list", params)
            for ch in data.get("channels", []):
                if ch.get("is_member") is False and ch.get("is_private"):
                    continue  # bot can't read this private channel
                out.append({
                    "id": ch["id"],
                    "name": ch.get("name", ch["id"]),
                    "is_private": bool(ch.get("is_private")),
                    "num_members": ch.get("num_members"),
                    "is_member": bool(ch.get("is_member")),
                })
            cursor = data.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
    out.sort(key=lambda x: (not x["is_member"], x["name"]))
    return out


def select_channels(channel_ids: list[str], lookback_days: int | None = None) -> dict:
    cfg = _load_config()
    cfg["channels"] = channel_ids
    if lookback_days is not None:
        cfg["lookback_days"] = lookback_days
    # reset cursors for newly selected channels so first sync pulls history
    cfg["cursors"] = {cid: cfg.get("cursors", {}).get(cid, "") for cid in channel_ids}
    _save_config(cfg)
    return {"channels": channel_ids, "lookback_days": cfg["lookback_days"]}


def get_status() -> dict:
    cfg = _load_config()
    return {
        "connected": bool(cfg.get("bot_token")),
        "team": cfg.get("team"),
        "channels": cfg.get("channels", []),
        "lookback_days": cfg.get("lookback_days", DEFAULT_LOOKBACK_DAYS),
        "poll_seconds": cfg.get("poll_seconds", DEFAULT_POLL_SECONDS),
        "cursors": cfg.get("cursors", {}),
        "last_sync": _last_sync_status,
    }


def disconnect() -> None:
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()


# ── Sync ──────────────────────────────────────────────────────────────────────

def _fetch_users(client: httpx.Client) -> dict[str, str]:
    """Returns user_id → display name."""
    out: dict[str, str] = {}
    cursor = ""
    while True:
        params: dict = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        try:
            data = _slack_get(client, "/users.list", params)
        except RuntimeError:
            return out  # users:read may not be granted; degrade gracefully
        for u in data.get("members", []):
            name = (
                u.get("profile", {}).get("display_name")
                or u.get("real_name")
                or u.get("name")
                or u["id"]
            )
            out[u["id"]] = name
        cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
    return out


def _format_thread(messages: list[dict], users: dict[str, str], channel_name: str) -> str:
    """Render Slack messages as a readable transcript."""
    lines = [f"# Slack thread in #{channel_name}", ""]
    for m in messages:
        ts = m.get("ts", "")
        try:
            dt = datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)
            tstr = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            tstr = ts
        user = users.get(m.get("user", ""), m.get("user", "unknown"))
        text = m.get("text", "")
        # Replace user mentions <@U123> with names
        for uid, uname in users.items():
            text = text.replace(f"<@{uid}>", f"@{uname}")
        lines.append(f"{user} {tstr}")
        lines.append(text.strip())
        lines.append("")
    return "\n".join(lines).strip()


def _group_threads(messages: list[dict]) -> list[list[dict]]:
    """Group messages by thread_ts. Top-level messages without replies become single-message threads."""
    groups: dict[str, list[dict]] = collections.OrderedDict()
    for m in messages:
        if m.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
            continue
        if not m.get("text"):
            continue
        key = m.get("thread_ts") or m.get("ts")
        groups.setdefault(key, []).append(m)
    return list(groups.values())


def sync_once(ingest_fn: Callable[[str, str, str], dict]) -> dict:
    """Pull new messages from each selected channel and ingest each thread as a source.

    `ingest_fn(kind, title, content) -> result_dict` — caller-supplied bridge to the
    main ingest pipeline; lets this module stay independent of the FastAPI app.
    """
    cfg = _load_config()
    token = cfg.get("bot_token")
    channel_ids: list[str] = cfg.get("channels", [])
    if not token or not channel_ids:
        return {"ingested": 0, "skipped": True, "reason": "no token or no channels"}

    if _last_sync_status["running"]:
        return {"ingested": 0, "skipped": True, "reason": "another sync is running"}

    _last_sync_status["running"] = True
    _last_sync_status["last_error"] = None
    ingested = 0
    errors: list[str] = []
    started = time.time()

    try:
        with _client(token) as c:
            users = _fetch_users(c)

            # Build channel_id → name lookup (best-effort, ignore failures)
            ch_names: dict[str, str] = {}
            try:
                for ch in list_channels(token):
                    ch_names[ch["id"]] = ch["name"]
            except Exception:
                pass

            lookback_seconds = cfg.get("lookback_days", DEFAULT_LOOKBACK_DAYS) * 86400
            now = time.time()
            cursors = dict(cfg.get("cursors", {}))

            for cid in channel_ids:
                ch_name = ch_names.get(cid, cid)
                last_ts = cursors.get(cid) or ""
                # If no cursor, start from now - lookback
                oldest = last_ts if last_ts else f"{now - lookback_seconds:.6f}"
                latest_seen = float(last_ts) if last_ts else 0.0

                # Pull channel history (paginated)
                msgs: list[dict] = []
                cursor = ""
                while True:
                    params: dict = {
                        "channel": cid,
                        "oldest": oldest,
                        "limit": 200,
                    }
                    if cursor:
                        params["cursor"] = cursor
                    try:
                        data = _slack_get(c, "/conversations.history", params)
                    except RuntimeError as e:
                        errors.append(f"{ch_name}: {e}")
                        break
                    msgs.extend(data.get("messages", []))
                    if not data.get("has_more"):
                        break
                    cursor = data.get("response_metadata", {}).get("next_cursor", "")
                    if not cursor:
                        break
                    time.sleep(0.3)  # rate-limit cushion

                # Pull replies for any thread parents
                threads = _group_threads(msgs)
                for group in threads:
                    parent = group[0]
                    if parent.get("reply_count", 0) > 0 and parent.get("thread_ts"):
                        try:
                            data = _slack_get(c, "/conversations.replies", {
                                "channel": cid,
                                "ts": parent["thread_ts"],
                                "limit": 200,
                            })
                            group[:] = data.get("messages", []) or group
                        except RuntimeError:
                            pass

                # Ingest each thread as a source
                for group in threads:
                    if not group:
                        continue
                    parent_ts = group[0].get("ts", "")
                    try:
                        latest_seen = max(latest_seen, float(parent_ts))
                    except Exception:
                        pass
                    try:
                        first_dt = datetime.datetime.fromtimestamp(
                            float(parent_ts), tz=datetime.timezone.utc
                        ).strftime("%Y-%m-%d %H:%M")
                    except Exception:
                        first_dt = parent_ts
                    title = f"#{ch_name} · {first_dt}"
                    content = _format_thread(group, users, ch_name)
                    if len(content) < 80:
                        continue  # skip noise
                    try:
                        ingest_fn("slack", title, content)
                        ingested += 1
                    except Exception as e:
                        errors.append(f"{ch_name} ingest: {e}")

                cursors[cid] = f"{latest_seen:.6f}" if latest_seen else oldest
                time.sleep(0.5)  # gentle on Slack

            # Persist updated cursors
            cfg["cursors"] = cursors
            _save_config(cfg)

        _last_sync_status["last_run_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        _last_sync_status["ingested"] = ingested
        if errors:
            _last_sync_status["last_error"] = " | ".join(errors[:5])
    except Exception as e:
        _last_sync_status["last_error"] = str(e)
        errors.append(str(e))
    finally:
        _last_sync_status["running"] = False

    return {
        "ingested": ingested,
        "errors": errors,
        "elapsed_seconds": round(time.time() - started, 2),
    }


# ── Background poll loop ──────────────────────────────────────────────────────

def _poll_loop(ingest_fn: Callable[[str, str, str], dict]) -> None:
    while not _stop_event.is_set():
        cfg = _load_config()
        interval = max(60, int(cfg.get("poll_seconds") or DEFAULT_POLL_SECONDS))
        if cfg.get("bot_token") and cfg.get("channels"):
            try:
                sync_once(ingest_fn)
            except Exception as e:
                _last_sync_status["last_error"] = str(e)
        # Sleep in 5s ticks so stop_event responds quickly
        for _ in range(interval // 5):
            if _stop_event.is_set():
                return
            time.sleep(5)


def start_poll_thread(ingest_fn: Callable[[str, str, str], dict]) -> None:
    global _poll_thread
    if _poll_thread and _poll_thread.is_alive():
        return
    _stop_event.clear()
    _poll_thread = threading.Thread(target=_poll_loop, args=(ingest_fn,), daemon=True, name="slack-poll")
    _poll_thread.start()


def stop_poll_thread() -> None:
    _stop_event.set()
