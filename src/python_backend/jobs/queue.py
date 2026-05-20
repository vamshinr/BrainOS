"""Async job queue: single-worker FIFO for LLM-bound ingest work."""
from __future__ import annotations
import uuid
import threading
import queue as _stdlib_queue
import collections
import datetime
import time
from typing import Optional
from core.logging import _utc_now_iso, _debug_event

class Job:
    def __init__(self, *, kind: str, title: str, handler, payload: Optional[dict] = None):
        self.id = str(uuid.uuid4())[:8]
        self.kind = kind                  # "ingest_text" | "ingest_file" | "ingest_image"
        self.title = title
        self.status = "queued"            # queued | running | completed | failed | canceled
        self.progress = 0.0               # 0..1
        self.step: Optional[str] = None   # human-readable current step
        self.error: Optional[str] = None
        self.result: Optional[dict] = None
        self.payload = payload or {}      # private — never returned via to_public()
        self.handler = handler
        self.created_at = _utc_now_iso()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.cancel_requested = False

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "step": self.step,
            "error": self.error,
            "result": self.result,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


class JobQueue:
    """Single-worker FIFO. submit() returns immediately. The background thread
    runs jobs serially. Listeners get live events for the SSE stream."""

    RECENT_LIMIT = 50

    def __init__(self):
        self._q: _stdlib_queue.Queue = _stdlib_queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._queue_order: list[str] = []
        self._active_id: Optional[str] = None
        self._recent_ids = collections.deque(maxlen=self.RECENT_LIMIT)
        self._lock = threading.Lock()
        self._listeners: list[_stdlib_queue.Queue] = []
        threading.Thread(target=self._run_worker, daemon=True, name="JobQueueWorker").start()

    def submit(self, *, kind: str, title: str, handler, payload: Optional[dict] = None) -> Job:
        job = Job(kind=kind, title=title, handler=handler, payload=payload)
        with self._lock:
            self._jobs[job.id] = job
            self._queue_order.append(job.id)
        self._q.put(job.id)
        self._notify("job.queued", job)
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status == "queued":
                job.status = "canceled"
                job.finished_at = _utc_now_iso()
                if job.id in self._queue_order:
                    self._queue_order.remove(job.id)
                self._recent_ids.append(job.id)
                self._notify("job.canceled", job)
                return True
            if job.status == "running":
                # Can't cleanly interrupt an in-flight LLM call. Mark a flag the
                # handler can poll between steps if it wants to abort early.
                job.cancel_requested = True
                return True
            return False

    def get(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        return job.to_public() if job else None

    def queue_position(self, job_id: str) -> int:
        with self._lock:
            try:
                return self._queue_order.index(job_id) + 1
            except ValueError:
                return 0

    def snapshot(self) -> dict:
        with self._lock:
            active = self._jobs[self._active_id].to_public() if self._active_id and self._active_id in self._jobs else None
            queued = [self._jobs[i].to_public() for i in self._queue_order if i in self._jobs]
            recent = [self._jobs[i].to_public() for i in reversed(self._recent_ids) if i in self._jobs]
            return {"active": active, "queued": queued, "recent": recent}

    def update_progress(self, job_id: str, *, progress: Optional[float] = None, step: Optional[str] = None):
        job = self._jobs.get(job_id)
        if not job:
            return
        if progress is not None:
            job.progress = max(0.0, min(1.0, float(progress)))
        if step is not None:
            job.step = step
        self._notify("job.progress", job)

    def listen(self) -> _stdlib_queue.Queue:
        q: _stdlib_queue.Queue = _stdlib_queue.Queue(maxsize=256)
        with self._lock:
            self._listeners.append(q)
        return q

    def unlisten(self, q):
        with self._lock:
            if q in self._listeners:
                self._listeners.remove(q)

    def _notify(self, event: str, job: Job):
        payload = {"event": event, "job": job.to_public()}
        with self._lock:
            dead = []
            for q in self._listeners:
                try:
                    q.put_nowait(payload)
                except _stdlib_queue.Full:
                    dead.append(q)
            for q in dead:
                self._listeners.remove(q)

    def _run_worker(self):
        while True:
            job_id = self._q.get()
            with self._lock:
                job = self._jobs.get(job_id)
                if not job or job.status != "queued":
                    continue
                self._active_id = job.id
                if job.id in self._queue_order:
                    self._queue_order.remove(job.id)
                job.status = "running"
                job.started_at = _utc_now_iso()
            self._notify("job.started", job)
            try:
                result = job.handler(job, self)
                job.result = result if isinstance(result, dict) else {"value": result}
                job.status = "completed"
                job.progress = 1.0
            except Exception as e:
                job.error = str(e)
                job.status = "failed"
                print(f"[BrainOS] job {job.id} ({job.kind}) failed: {e}")
            finally:
                job.finished_at = _utc_now_iso()
                with self._lock:
                    self._active_id = None
                    self._recent_ids.append(job.id)
                self._notify("job.finished", job)


job_queue = JobQueue()


# ── Job handlers ─────────────────────────────────────────────────────────────
# Each handler takes (job, queue) and returns a result dict. The queue arg is
# used to publish step/progress updates the UI dock subscribes to.
