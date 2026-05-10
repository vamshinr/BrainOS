from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
SLACK_DATA_DIR = DATA_DIR / "slack"
TOKEN_FILE = SLACK_DATA_DIR / "oauth_tokens.json"
CHANNEL_MAP_FILE = SLACK_DATA_DIR / "channel_map.json"


@dataclass(frozen=True)
class SlackMCPConfig:
    access_token: str | None
    app_id: str | None
    signing_secret: str | None
    bot_user_id: str | None
    allowed_channels: set[str]
    auto_answer_channels: set[str]
    auto_answer_prefixes: tuple[str, ...]
    default_department: str
    channel_map: dict[str, str]
    endpoint: str = "https://mcp.slack.com/mcp"

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def channel_allowed(self, channel_id: str | None) -> bool:
        if not self.allowed_channels:
            return True
        return bool(channel_id and channel_id in self.allowed_channels)

    def department_for_channel(self, channel_id: str | None, fallback: str | None = None) -> str:
        if fallback:
            return fallback
        if channel_id and channel_id in self.channel_map:
            return self.channel_map[channel_id]
        return self.default_department


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_slack_config() -> SlackMCPConfig:
    token_data = _read_json(TOKEN_FILE)
    channel_map = _read_json(CHANNEL_MAP_FILE)
    allowed = {
        item.strip()
        for item in os.getenv("SLACK_ALLOWED_CHANNELS", "").split(",")
        if item.strip()
    }
    auto_answer_channels = {
        item.strip()
        for item in os.getenv("SLACK_AUTO_ANSWER_CHANNELS", "").split(",")
        if item.strip()
    }
    auto_answer_prefixes = tuple(
        item.strip().lower()
        for item in os.getenv("SLACK_AUTO_ANSWER_PREFIXES", "brainos:,brainos,?").split(",")
        if item.strip()
    )
    return SlackMCPConfig(
        access_token=os.getenv("SLACK_MCP_ACCESS_TOKEN") or token_data.get("access_token"),
        app_id=os.getenv("SLACK_MCP_APP_ID") or token_data.get("app_id"),
        signing_secret=os.getenv("SLACK_SIGNING_SECRET") or token_data.get("signing_secret"),
        bot_user_id=os.getenv("SLACK_BOT_USER_ID") or token_data.get("bot_user_id"),
        allowed_channels=allowed,
        auto_answer_channels=auto_answer_channels,
        auto_answer_prefixes=auto_answer_prefixes,
        default_department=os.getenv("SLACK_DEFAULT_DEPARTMENT", "general").strip() or "general",
        channel_map={str(k): str(v) for k, v in channel_map.items()},
        endpoint=os.getenv("SLACK_MCP_ENDPOINT", "https://mcp.slack.com/mcp"),
    )
