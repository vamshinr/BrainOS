from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, Form, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from slack_mcp.auth import load_slack_config
from slack_mcp.bot import answer_for_slack
from slack_mcp.canvas import export_canvas
from slack_mcp.client import SlackMCPClient, SlackMCPError
from slack_mcp.ingest import ingest_slack_document
from slack_mcp.normalizer import build_source_document


class SlackThreadIngestRequest(BaseModel):
    channel_id: str
    thread_ts: str
    channel_name: Optional[str] = None
    department: Optional[str] = None
    model: Optional[str] = None


class SlackChannelIngestRequest(BaseModel):
    channel_id: str
    channel_name: Optional[str] = None
    department: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=200)
    model: Optional[str] = None


class SlackSearchIngestRequest(BaseModel):
    query: str
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    department: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    model: Optional[str] = None


class SlackAskRequest(BaseModel):
    channel_id: str
    question: str
    department: Optional[str] = None
    send_to_slack: bool = False
    thread_ts: Optional[str] = None
    model: Optional[str] = None


class SlackSendMessageRequest(BaseModel):
    channel_id: str
    text: str
    thread_ts: Optional[str] = None


class SlackCanvasRequest(BaseModel):
    title: str
    markdown: str
    department: Optional[str] = None
    canvas_id: Optional[str] = None


class ChannelMapRequest(BaseModel):
    channel_id: str
    department: str


def create_slack_router(
    *,
    ingest_agent: Any,
    struct_agent: Any,
    exec_agent: Any,
    feedback_agent: Any,
    chunk_text: Callable[..., list[str]],
    max_extraction_chars: int,
    utc_now_iso: Callable[[], str],
    debug_event: Callable[..., None],
    is_sensitive: Callable[[str], str | None],
) -> APIRouter:
    router = APIRouter(prefix="/api/slack", tags=["slack-mcp"])

    def _client() -> SlackMCPClient:
        config = load_slack_config()
        if not config.configured:
            raise HTTPException(status_code=503, detail="SLACK_MCP_ACCESS_TOKEN is not configured.")
        return SlackMCPClient(config)

    def _ensure_channel_allowed(client: SlackMCPClient, channel_id: str | None):
        if not client.config.channel_allowed(channel_id):
            raise HTTPException(status_code=403, detail=f"Slack channel '{channel_id}' is not allowed.")

    async def _verify_slack_signature(
        request: Request,
        timestamp: str | None,
        signature: str | None,
    ) -> bytes:
        body = await request.body()
        config = load_slack_config()
        if not config.signing_secret:
            debug_event(
                "slack.signature.skipped",
                "SLACK_SIGNING_SECRET not configured; accepting Slack form request in local/dev mode",
            )
            return body
        if not timestamp or not signature:
            raise HTTPException(status_code=401, detail="Missing Slack signature headers.")
        try:
            request_ts = int(timestamp)
        except ValueError as e:
            raise HTTPException(status_code=401, detail="Invalid Slack timestamp.") from e
        if abs(time.time() - request_ts) > 60 * 5:
            raise HTTPException(status_code=401, detail="Stale Slack request timestamp.")
        base = f"v0:{timestamp}:{body.decode('utf-8')}".encode("utf-8")
        expected = "v0=" + hmac.new(
            config.signing_secret.encode("utf-8"),
            base,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid Slack signature.")
        return body

    @router.get("/health")
    def health():
        config = load_slack_config()
        payload = {
            "configured": config.configured,
            "endpoint": config.endpoint,
            "app_id_configured": bool(config.app_id),
            "signing_secret_configured": bool(config.signing_secret),
            "bot_user_id_configured": bool(config.bot_user_id),
            "allowed_channels": sorted(config.allowed_channels),
            "auto_answer_channels": sorted(config.auto_answer_channels),
            "auto_answer_prefixes": list(config.auto_answer_prefixes),
            "default_department": config.default_department,
            "channel_map_entries": len(config.channel_map),
        }
        if not config.configured:
            return payload
        try:
            tools = SlackMCPClient(config).list_tools()
            payload["mcp_ok"] = True
            payload["tools"] = tools
        except Exception as e:
            payload["mcp_ok"] = False
            payload["error"] = str(e)
        return payload

    @router.get("/channel_map")
    def channel_map():
        config = load_slack_config()
        return {
            "default_department": config.default_department,
            "channel_map": config.channel_map,
            "allowed_channels": sorted(config.allowed_channels),
        }

    @router.post("/channel_map")
    def set_channel_map(req: ChannelMapRequest):
        from slack_mcp.auth import CHANNEL_MAP_FILE, SLACK_DATA_DIR
        SLACK_DATA_DIR.mkdir(parents=True, exist_ok=True)
        config = load_slack_config()
        mapping = dict(config.channel_map)
        mapping[req.channel_id] = req.department
        CHANNEL_MAP_FILE.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        debug_event(
            "slack.channel_map.update",
            "Updated Slack channel department mapping",
            channel_id=req.channel_id,
            department=req.department,
        )
        return {"channel_map": mapping}

    @router.post("/ingest_thread")
    def ingest_thread(req: SlackThreadIngestRequest):
        client = _client()
        _ensure_channel_allowed(client, req.channel_id)
        department = client.config.department_for_channel(req.channel_id, req.department)
        debug_event(
            "slack.thread.read",
            "Reading Slack thread through MCP",
            channel_id=req.channel_id,
            thread_ts=req.thread_ts,
            department=department,
        )
        try:
            payload = client.read_thread(req.channel_id, req.thread_ts)
        except SlackMCPError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        doc = build_source_document(
            payload,
            channel_id=req.channel_id,
            channel_name=req.channel_name,
            thread_ts=req.thread_ts,
            department=department,
            title_prefix="Slack Thread",
        )
        result = ingest_slack_document(
            doc,
            ingest_agent=ingest_agent,
            struct_agent=struct_agent,
            chunk_text=chunk_text,
            max_extraction_chars=max_extraction_chars,
            utc_now_iso=utc_now_iso,
            debug_event=debug_event,
            model=req.model,
        )
        result["slack"]["mcp_action"] = "read_thread"
        return result

    @router.post("/ingest_channel")
    def ingest_channel(req: SlackChannelIngestRequest):
        client = _client()
        _ensure_channel_allowed(client, req.channel_id)
        department = client.config.department_for_channel(req.channel_id, req.department)
        debug_event(
            "slack.channel.read",
            "Reading Slack channel through MCP",
            channel_id=req.channel_id,
            limit=req.limit,
            department=department,
        )
        try:
            payload = client.read_channel(req.channel_id, limit=req.limit)
        except SlackMCPError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        doc = build_source_document(
            payload,
            channel_id=req.channel_id,
            channel_name=req.channel_name,
            department=department,
            title_prefix="Slack Channel",
        )
        result = ingest_slack_document(
            doc,
            ingest_agent=ingest_agent,
            struct_agent=struct_agent,
            chunk_text=chunk_text,
            max_extraction_chars=max_extraction_chars,
            utc_now_iso=utc_now_iso,
            debug_event=debug_event,
            model=req.model,
        )
        result["slack"]["mcp_action"] = "read_channel"
        return result

    @router.post("/search_ingest")
    def search_ingest(req: SlackSearchIngestRequest):
        client = _client()
        if req.channel_id:
            _ensure_channel_allowed(client, req.channel_id)
        department = client.config.department_for_channel(req.channel_id, req.department)
        debug_event(
            "slack.search",
            "Searching Slack through MCP for ingestion",
            query=req.query,
            channel_id=req.channel_id,
            limit=req.limit,
            department=department,
        )
        try:
            payload = client.search_messages(req.query, channel_id=req.channel_id, limit=req.limit)
        except SlackMCPError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        doc = build_source_document(
            payload,
            channel_id=req.channel_id,
            channel_name=req.channel_name,
            department=department,
            title_prefix=f"Slack Search: {req.query[:80]}",
        )
        result = ingest_slack_document(
            doc,
            ingest_agent=ingest_agent,
            struct_agent=struct_agent,
            chunk_text=chunk_text,
            max_extraction_chars=max_extraction_chars,
            utc_now_iso=utc_now_iso,
            debug_event=debug_event,
            model=req.model,
        )
        result["slack"]["mcp_action"] = "search_messages"
        return result

    @router.post("/ask")
    def ask(req: SlackAskRequest):
        client = _client()
        _ensure_channel_allowed(client, req.channel_id)
        debug_event(
            "slack.ask.start",
            "Answering Slack question through BrainOS",
            channel_id=req.channel_id,
            send_to_slack=req.send_to_slack,
            question=req.question,
        )
        result = answer_for_slack(
            req.question,
            exec_agent=exec_agent,
            feedback_agent=feedback_agent,
            is_sensitive=is_sensitive,
            debug_event=debug_event,
            model=req.model,
        )
        if req.send_to_slack:
            try:
                send_result = client.send_message(
                    req.channel_id,
                    result["slack_text"],
                    thread_ts=req.thread_ts,
                )
                result["slack_send"] = send_result
            except SlackMCPError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
        else:
            result["slack_send"] = None
        return result

    @router.post("/send_message")
    def send_message(req: SlackSendMessageRequest):
        client = _client()
        _ensure_channel_allowed(client, req.channel_id)
        debug_event("slack.send", "Sending Slack message through MCP", channel_id=req.channel_id)
        try:
            return client.send_message(req.channel_id, req.text, thread_ts=req.thread_ts)
        except SlackMCPError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.post("/export_canvas")
    def canvas(req: SlackCanvasRequest):
        client = _client()
        debug_event("slack.canvas.export", "Exporting BrainOS markdown to Slack canvas", title=req.title)
        try:
            return export_canvas(
                client=client,
                title=req.title,
                markdown=req.markdown,
                department=req.department,
                canvas_id=req.canvas_id,
            )
        except SlackMCPError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.post("/slash")
    async def slash_command(
        request: Request,
        x_slack_request_timestamp: Optional[str] = Header(None),
        x_slack_signature: Optional[str] = Header(None),
        channel_id: str = Form(...),
        text: str = Form(""),
        command: str = Form("/brainos"),
        user_id: str = Form(""),
    ):
        await _verify_slack_signature(request, x_slack_request_timestamp, x_slack_signature)
        client = _client()
        _ensure_channel_allowed(client, channel_id)
        raw_text = text.strip()
        lower = raw_text.lower()
        debug_event(
            "slack.slash",
            "Received Slack slash command",
            command=command,
            channel_id=channel_id,
            user_id=user_id,
            text=raw_text,
        )

        if not raw_text or lower in {"help", "--help"}:
            return {
                "response_type": "ephemeral",
                "text": (
                    "BrainOS commands:\n"
                    "`/brainos ask <question>`\n"
                    "`/brainos ingest-channel [limit]`\n"
                    "`/brainos search-ingest <query>`\n"
                    "`/brainos post <question>`"
                ),
            }

        if lower.startswith("ask "):
            question = raw_text[4:].strip()
            result = answer_for_slack(
                question,
                exec_agent=exec_agent,
                feedback_agent=feedback_agent,
                is_sensitive=is_sensitive,
                debug_event=debug_event,
            )
            return {"response_type": "ephemeral", "text": result["slack_text"]}

        if lower.startswith("post "):
            question = raw_text[5:].strip()
            result = answer_for_slack(
                question,
                exec_agent=exec_agent,
                feedback_agent=feedback_agent,
                is_sensitive=is_sensitive,
                debug_event=debug_event,
            )
            try:
                client.send_message(channel_id, result["slack_text"])
            except SlackMCPError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
            return {"response_type": "ephemeral", "text": "Posted BrainOS answer to this channel."}

        if lower.startswith("ingest-channel"):
            parts = raw_text.split()
            limit = 50
            if len(parts) > 1 and parts[1].isdigit():
                limit = max(1, min(200, int(parts[1])))
            department = client.config.department_for_channel(channel_id)
            try:
                payload = client.read_channel(channel_id, limit=limit)
            except SlackMCPError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
            doc = build_source_document(
                payload,
                channel_id=channel_id,
                department=department,
                title_prefix="Slack Channel",
            )
            result = ingest_slack_document(
                doc,
                ingest_agent=ingest_agent,
                struct_agent=struct_agent,
                chunk_text=chunk_text,
                max_extraction_chars=max_extraction_chars,
                utc_now_iso=utc_now_iso,
                debug_event=debug_event,
            )
            return {
                "response_type": "ephemeral",
                "text": (
                    f"Ingested Slack channel context into BrainOS. "
                    f"Source `{result['source_id']}`, units: {result['units_stored']}, "
                    f"entities: {result['entities_stored']}, relationships: {result['relationships_stored']}."
                ),
            }

        if lower.startswith("search-ingest "):
            query = raw_text[len("search-ingest "):].strip()
            department = client.config.department_for_channel(channel_id)
            try:
                payload = client.search_messages(query, channel_id=channel_id, limit=25)
            except SlackMCPError as e:
                raise HTTPException(status_code=502, detail=str(e)) from e
            doc = build_source_document(
                payload,
                channel_id=channel_id,
                department=department,
                title_prefix=f"Slack Search: {query[:80]}",
            )
            result = ingest_slack_document(
                doc,
                ingest_agent=ingest_agent,
                struct_agent=struct_agent,
                chunk_text=chunk_text,
                max_extraction_chars=max_extraction_chars,
                utc_now_iso=utc_now_iso,
                debug_event=debug_event,
            )
            return {
                "response_type": "ephemeral",
                "text": f"Ingested search results into BrainOS as source `{result['source_id']}`.",
            }

        return {
            "response_type": "ephemeral",
            "text": "Unknown BrainOS command. Try `/brainos help`.",
        }

    def _strip_slack_mentions(text: str, bot_user_id: str | None) -> str:
        cleaned = text.strip()
        if bot_user_id:
            cleaned = re.sub(rf"<@{re.escape(bot_user_id)}>\s*", "", cleaned).strip()
        return re.sub(r"<@[A-Z0-9]+>\s*", "", cleaned).strip()

    def _auto_answer_question(text: str, prefixes: tuple[str, ...]) -> str | None:
        stripped = text.strip()
        lowered = stripped.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                if prefix[-1:].isalnum() and len(stripped) > len(prefix) and stripped[len(prefix)].isalnum():
                    continue
                return stripped[len(prefix):].strip(" :-\t")
        return None

    @router.post("/events")
    async def events(
        request: Request,
        x_slack_request_timestamp: Optional[str] = Header(None),
        x_slack_signature: Optional[str] = Header(None),
    ):
        await _verify_slack_signature(request, x_slack_request_timestamp, x_slack_signature)
        body = await request.json()
        if body.get("type") == "url_verification":
            return PlainTextResponse(body.get("challenge", ""))
        client = _client()
        event = body.get("event") or {}
        event_type = event.get("type")
        debug_event(
            "slack.events.received",
            "Received Slack event callback",
            event_type=event_type,
            channel_id=event.get("channel"),
        )
        if event_type not in {"app_mention", "message"}:
            return {"ok": True, "ignored": "unsupported_event_type"}
        if event.get("subtype") or event.get("bot_id"):
            return {"ok": True, "ignored": "bot_or_subtype_event"}
        if client.config.bot_user_id and event.get("user") == client.config.bot_user_id:
            return {"ok": True, "ignored": "self_event"}

        channel_id = event.get("channel")
        _ensure_channel_allowed(client, channel_id)

        text = _strip_slack_mentions(str(event.get("text") or ""), client.config.bot_user_id)
        if event_type == "app_mention":
            question = text
        elif channel_id in client.config.auto_answer_channels:
            question = _auto_answer_question(text, client.config.auto_answer_prefixes)
        else:
            return {"ok": True, "ignored": "auto_answer_not_enabled_for_channel"}

        if not question:
            return {"ok": True, "ignored": "empty_question"}

        debug_event(
            "slack.events.auto_answer.start",
            "Answering Slack event through BrainOS",
            channel_id=channel_id,
            event_type=event_type,
            question=question,
        )
        result = answer_for_slack(
            question,
            exec_agent=exec_agent,
            feedback_agent=feedback_agent,
            is_sensitive=is_sensitive,
            debug_event=debug_event,
        )
        thread_ts = event.get("thread_ts") or event.get("ts")
        try:
            send_result = client.send_message(channel_id, result["slack_text"], thread_ts=thread_ts)
        except SlackMCPError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {
            "ok": True,
            "answered": True,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "slack_send": send_result,
        }

    return router
