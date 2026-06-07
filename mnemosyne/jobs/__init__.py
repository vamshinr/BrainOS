"""Async ingestion job queue: an in-memory queue + worker pool in front of the
synchronous MnemosyneService.ingest, streamed to the UI's QueueDock over SSE."""

from .manager import JobManager
from .models import Job, make_title, now_iso

__all__ = ["JobManager", "Job", "make_title", "now_iso"]
