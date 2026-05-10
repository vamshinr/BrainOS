from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.request
from typing import Any

from .auth import SlackMCPConfig
from .rate_limits import SlackRateLimitError, with_backoff


class SlackMCPError(RuntimeError):
    pass


def _compact_args(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


class SlackMCPClient:
    """Minimal JSON-RPC 2.0 client for Slack MCP over Streamable HTTP."""

    def __init__(self, config: SlackMCPConfig):
        self.config = config

    def _headers(self) -> dict[str, str]:
        if not self.config.access_token:
            raise SlackMCPError("SLACK_MCP_ACCESS_TOKEN is not configured.")
        headers = {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.config.app_id:
            headers["X-Slack-App-ID"] = self.config.app_id
        return headers

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        def _send() -> Any:
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params or {},
            }
            req = urllib.request.Request(
                self.config.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=self._headers(),
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    body = resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                retry_after = e.headers.get("Retry-After")
                if e.code == 429:
                    raise SlackRateLimitError(
                        "Slack MCP rate limit exceeded.",
                        float(retry_after) if retry_after else None,
                    )
                detail = e.read().decode("utf-8", errors="replace")
                raise SlackMCPError(f"Slack MCP HTTP {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                raise SlackMCPError(f"Slack MCP connection failed: {e}") from e

            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                raise SlackMCPError(f"Slack MCP returned non-JSON response: {body[:200]}") from e
            if data.get("error"):
                raise SlackMCPError(f"Slack MCP error: {data['error']}")
            return data.get("result")

        return with_backoff(_send)

    def list_tools(self) -> Any:
        return self.request("tools/list")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def call_first_tool(self, names: list[str], arguments: dict[str, Any] | None = None) -> Any:
        last_error: SlackMCPError | None = None
        for name in names:
            try:
                return self.call_tool(name, arguments)
            except SlackMCPError as e:
                last_error = e
                if "tool_not_found" not in str(e):
                    raise
        raise last_error or SlackMCPError(f"No Slack MCP tool found from aliases: {names}")

    def call_tool_variants(self, variants: list[tuple[str, dict[str, Any]]]) -> Any:
        last_error: SlackMCPError | None = None
        retryable_markers = ("tool_not_found", "no_text", "missing", "invalid_arguments")
        for name, arguments in variants:
            try:
                return self.call_tool(name, arguments)
            except SlackMCPError as e:
                last_error = e
                if not any(marker in str(e) for marker in retryable_markers):
                    raise
        raise last_error or SlackMCPError("No Slack MCP tool variant succeeded.")

    def search_messages(self, query: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_search", "slack_search_messages", "search_messages"],
            _compact_args({"query": query, **kwargs}),
        )

    def read_channel(self, channel_id: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_read_channel", "slack_get_channel_history", "read_channel"],
            _compact_args({"channel_id": channel_id, **kwargs}),
        )

    def read_thread(self, channel_id: str, thread_ts: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_read_thread", "slack_get_thread", "read_thread"],
            _compact_args({"channel_id": channel_id, "thread_ts": thread_ts, **kwargs}),
        )

    def send_message(self, channel_id: str, text: str, **kwargs: Any) -> Any:
        extra = dict(kwargs)
        return self.call_tool_variants([
            ("slack_send_message", _compact_args({"channel_id": channel_id, "text": text, **extra})),
            ("slack_send_message", _compact_args({"channel_id": channel_id, "message": text, **extra})),
            ("slack_send_message", _compact_args({"channel": channel_id, "text": text, **extra})),
            ("slack_send_message", _compact_args({"channel": channel_id, "message": text, **extra})),
            ("send_message", _compact_args({"channel_id": channel_id, "text": text, **extra})),
            ("send_message", _compact_args({"channel_id": channel_id, "message": text, **extra})),
            ("send_message", _compact_args({"channel": channel_id, "text": text, **extra})),
            ("send_message", _compact_args({"channel": channel_id, "message": text, **extra})),
        ])

    def create_canvas(self, title: str, markdown: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_create_canvas", "create_canvas"],
            _compact_args({"title": title, "markdown": markdown, **kwargs}),
        )

    def update_canvas(self, canvas_id: str, markdown: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_update_canvas", "update_canvas"],
            _compact_args({"canvas_id": canvas_id, "markdown": markdown, **kwargs}),
        )

    def read_canvas(self, canvas_id: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_read_canvas", "read_canvas"],
            _compact_args({"canvas_id": canvas_id, **kwargs}),
        )

    def search_users(self, query: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_search_users", "search_users"],
            _compact_args({"query": query, **kwargs}),
        )

    def search_channels(self, query: str, **kwargs: Any) -> Any:
        return self.call_first_tool(
            ["slack_search_channels", "search_channels"],
            _compact_args({"query": query, **kwargs}),
        )
