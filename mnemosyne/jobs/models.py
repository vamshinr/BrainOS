"""Job record + helpers. `to_public()` returns exactly the camelCase fields the
QueueDock consumes; the raw text payload is never serialized."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_title(title: str, source_id: str, text: str) -> str:
    """Label shown in the dock: request title, else source_id, else a text
    snippet (<=40 chars), else 'Untitled'."""
    chosen = (title or "").strip() or (source_id or "").strip()
    if chosen:
        return chosen
    snippet = " ".join(text.split())[:40].strip()
    return snippet or "Untitled"


@dataclass
class Job:
    id: str
    kind: str            # "ingest_text" | "ingest_file"
    title: str
    text: str            # private payload — never serialized
    source_id: str = ""
    status: str = "queued"  # queued | running | completed | failed | canceled
    progress: float = 0.0   # 0..1
    step: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 4),
            "step": self.step,
            "error": self.error,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }
