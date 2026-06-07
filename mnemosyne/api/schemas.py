"""Request schemas for the HTTP API (Pydantic v2). Responses are built by the service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    text: str = Field(..., description="raw text: a chat turn, log block, or document")
    source_id: str = Field("", description="which document/session this came from")
    reference_time: Optional[datetime] = Field(
        None, description="'now' for resolving relative times; defaults to server time"
    )


class RetrieveRequest(BaseModel):
    query: str
    k: int = 5
    mode: Literal["causal", "associative"] = "causal"


class ManualEdgeRequest(BaseModel):
    cause_id: str
    effect_id: str
    relation: str = "caused"
    confidence: float = 1.0
    evidence: str = "manual"
