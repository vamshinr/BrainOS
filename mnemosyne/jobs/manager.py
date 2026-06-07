"""In-memory job queue + thread-pool workers.

The worker runs the injected (synchronous) ingest function in a thread so the
FastAPI event loop — and the SSE stream feeding the dock — never blocks. A
monotonic `version` counter is bumped on every state change; the SSE endpoint
polls it to decide when to push a fresh snapshot (multi-subscriber safe)."""

from __future__ import annotations

import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional
from uuid import uuid4

from .models import Job, make_title, now_iso

# ingest_fn(text, source_id, on_progress) -> result (ignored)
IngestFn = Callable[[str, str, Callable[[float, str], None]], Any]


class JobManager:
    def __init__(
        self, ingest_fn: IngestFn, *, workers: int = 2, recent_limit: int = 20
    ) -> None:
        self._ingest = ingest_fn
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queued: deque[str] = deque()
        self._running: set[str] = set()
        self._recent: deque[str] = deque(maxlen=max(1, recent_limit))
        self._version = 0
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="ingest-worker"
        )

    # ---------------------------------------------------------------- enqueue
    def enqueue(
        self, *, text: str, source_id: str = "", title: str = "", kind: str = "ingest_text"
    ) -> Job:
        job = Job(
            id=uuid4().hex,
            kind=kind,
            title=make_title(title, source_id, text),
            text=text,
            source_id=source_id,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._queued.append(job.id)
            self._version += 1
        self._pool.submit(self._run, job.id)
        return job

    # ----------------------------------------------------------------- worker
    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "canceled":
                self._discard_queued(job_id)
                return
            self._discard_queued(job_id)
            job.status = "running"
            job.started_at = now_iso()
            job.step = "Starting"
            self._running.add(job_id)
            self._version += 1

        def on_progress(fraction: float, step: str) -> None:
            with self._lock:
                j = self._jobs.get(job_id)
                if j is None or j.status != "running":
                    return
                j.progress = max(0.0, min(1.0, fraction))
                j.step = step
                self._version += 1

        try:
            self._ingest(job.text, job.source_id, on_progress)
            with self._lock:
                job.status = "completed"
                job.progress = 1.0
                job.step = "Done"
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.step = None
        finally:
            with self._lock:
                job.finished_at = now_iso()
                self._running.discard(job_id)
                self._recent.appendleft(job_id)
                self._version += 1

    def _discard_queued(self, job_id: str) -> None:
        try:
            self._queued.remove(job_id)
        except ValueError:
            pass

    # ----------------------------------------------------------------- cancel
    def cancel(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == "queued":
                job.status = "canceled"
                job.finished_at = now_iso()
                self._discard_queued(job_id)
                self._recent.appendleft(job_id)
                self._version += 1
            return job

    # ------------------------------------------------------------------ reads
    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def version(self) -> int:
        with self._lock:
            return self._version

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = [self._jobs[i].to_public() for i in self._running if i in self._jobs]
            queued = [self._jobs[i].to_public() for i in self._queued if i in self._jobs]
            recent = [self._jobs[i].to_public() for i in self._recent if i in self._jobs]
        active.sort(key=lambda j: j.get("startedAt") or "")
        return {"active": active, "queued": queued, "recent": recent}
