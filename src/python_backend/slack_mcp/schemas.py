from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any, Optional


class SlackMessage(BaseModel):
    user: str = "unknown"
    text: str = ""
    ts: str = ""
    datetime: Optional[str] = None
    permalink: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SlackSourceDocument(BaseModel):
    title: str
    content: str
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    thread_ts: Optional[str] = None
    department: str = "general"
    url: Optional[str] = None
    message_count: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class SlackIngestResult(BaseModel):
    source_id: str
    units_extracted: int
    entities_extracted: int
    relationships_extracted: int
    units_stored: int
    entities_stored: int
    relationships_stored: int
    raw_chunks_stored: int = 0
    brain_totals: dict[str, Any] = Field(default_factory=dict)
    slack: dict[str, Any] = Field(default_factory=dict)

