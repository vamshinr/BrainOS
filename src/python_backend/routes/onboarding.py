"""Customer-facing setup wizard endpoints (/api/onboarding/*)."""
from __future__ import annotations
import json
import os
import time
import threading
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from storage.brain import _read_brain
from core.logging import _debug_event, _utc_now_iso
from config import (
    DATA_DIR, ONBOARDING_FILE, SLACK_TOKEN_FILE, SLACK_CHANNEL_MAP_FILE,
)

router = APIRouter()

_DOC_KINDS = {"doc", "pdf", "file", "text", "code", "image"}

def _read_onboarding_record() -> dict:
    try:
        with open(ONBOARDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _write_onboarding_record(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ONBOARDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


_DOC_KINDS = {"doc", "pdf", "file", "text", "code", "image"}


@router.get("/api/onboarding/state")
def onboarding_state():
    """Derived onboarding state — fresh on every request from the actual brain
    + Slack config. Front-end uses this to gate the dashboard.

    "Slack ready" means: we have *some* way to talk to Slack AND at least one
    channel to listen to. The wizard intentionally only collects a bot token
    (xoxb-…) and skips the MCP user token, so cfg.configured (which only
    looks at the MCP access_token) isn't sufficient on its own. A bot token
    discovered by the poller's resolver counts just as much.
    """
    from slack_mcp.web_poller import _bot_token
    brain = _read_brain()
    sources = brain.get("sources", []) or []
    doc_sources = [s for s in sources if (s.get("kind") or "").lower() in _DOC_KINDS]
    cfg = load_slack_config()
    slack_channels = sorted(cfg.realtime_ingest_channels) or sorted(cfg.channel_map.keys()) or sorted(cfg.allowed_channels)
    has_bot_token = bool(_bot_token())
    slack_configured = bool(cfg.configured) or has_bot_token
    docs_ready = len(doc_sources) > 0
    slack_ready = slack_configured and bool(slack_channels)
    record = _read_onboarding_record()
    completed_at = record.get("completedAt")
    return {
        "docsReady": docs_ready,
        "slackReady": slack_ready,
        "docsCount": len(doc_sources),
        "slackChannels": slack_channels,
        "slackConfigured": slack_configured,
        "completedAt": completed_at,
        "complete": bool(completed_at) and docs_ready and slack_ready,
    }


@router.post("/api/onboarding/complete")
def onboarding_complete():
    """Mark onboarding done. Idempotent."""
    record = _read_onboarding_record()
    if not record.get("completedAt"):
        record["completedAt"] = _utc_now_iso()
    _write_onboarding_record(record)
    return record


@router.post("/api/onboarding/reset")
def onboarding_reset():
    """Wipe the completion marker so the wizard shows again. Brain & Slack
    config stay intact."""
    try:
        os.remove(ONBOARDING_FILE)
    except FileNotFoundError:
        pass
    return {"ok": True}


@router.post("/api/onboarding/slack/save")
async def onboarding_save_slack(request: Request):
    """Minimal Slack setup. Requires only a bot token (xoxb-…) and one or
    more channel IDs. Validates against Slack auth.test, persists to JSON,
    bumps env so the poller picks them up on its next cycle."""
    body = await request.json()
    bot_token = str(body.get("bot_token") or "").strip()
    channels = body.get("channels") or []
    if isinstance(channels, str):
        channels = [c.strip() for c in channels.split(",") if c.strip()]
    default_dept = (str(body.get("default_department") or "general")).strip() or "general"

    if not bot_token.startswith("xoxb-"):
        raise HTTPException(status_code=400, detail="bot_token must start with xoxb-")
    if not isinstance(channels, list) or not channels:
        raise HTTPException(status_code=400, detail="channels must be a non-empty list")

    # Validate by calling Slack auth.test. Surfaces invalid tokens immediately
    # to the UI rather than failing silently in the poller.
    async with httpx.AsyncClient(timeout=15.0) as c:
        try:
            r = await c.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
            j = r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"slack unreachable: {e}") from e
    if not j.get("ok"):
        raise HTTPException(status_code=400, detail=f"slack auth.test failed: {j.get('error')}")

    bot_user_id = j.get("user_id")
    team_id = j.get("team_id")
    team_name = j.get("team")

    # Persist token + bot user id to JSON. The web poller reads from here when
    # SLACK_BOT_TOKEN env isn't set; auth.py also reads from here for the MCP
    # access token fallback chain.
    os.makedirs(os.path.dirname(SLACK_TOKEN_FILE), exist_ok=True)
    existing = {}
    try:
        with open(SLACK_TOKEN_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f) or {}
    except FileNotFoundError:
        pass
    existing["bot_token"] = bot_token
    existing["bot_user_id"] = bot_user_id
    existing["team_id"] = team_id
    existing["team_name"] = team_name
    with open(SLACK_TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    # Map every channel to the chosen default department.
    cmap = {}
    try:
        with open(SLACK_CHANNEL_MAP_FILE, "r", encoding="utf-8") as f:
            cmap = json.load(f) or {}
    except FileNotFoundError:
        pass
    for ch in channels:
        cmap[ch] = cmap.get(ch) or default_dept
    with open(SLACK_CHANNEL_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(cmap, f, indent=2)

    # Bump env so the poller's next config_loader() call sees these channels.
    def _merge_env(key: str, new_items: list[str]) -> None:
        existing_items = {x.strip() for x in (os.environ.get(key) or "").split(",") if x.strip()}
        existing_items.update(new_items)
        os.environ[key] = ",".join(sorted(existing_items))

    _merge_env("SLACK_ALLOWED_CHANNELS", channels)
    _merge_env("SLACK_REALTIME_INGEST_CHANNELS", channels)
    if not os.getenv("SLACK_DEFAULT_DEPARTMENT"):
        os.environ["SLACK_DEFAULT_DEPARTMENT"] = default_dept

    # Backfill the most recent messages for each channel so the brain has
    # context immediately rather than waiting for new traffic.
    backfill_summary = []
    async with httpx.AsyncClient(timeout=30.0) as c:
        for ch in channels:
            try:
                rr = await c.get(
                    "https://slack.com/api/conversations.history",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    params={"channel": ch, "limit": 50},
                )
                jj = rr.json()
                if jj.get("ok"):
                    backfill_summary.append({"channel_id": ch, "fetched": len(jj.get("messages") or [])})
                else:
                    backfill_summary.append({"channel_id": ch, "error": jj.get("error")})
            except Exception as e:
                backfill_summary.append({"channel_id": ch, "error": str(e)})

    return {
        "ok": True,
        "bot_user_id": bot_user_id,
        "team_id": team_id,
        "team_name": team_name,
        "channels": sorted(channels),
        "default_department": default_dept,
        "backfill": backfill_summary,
    }


