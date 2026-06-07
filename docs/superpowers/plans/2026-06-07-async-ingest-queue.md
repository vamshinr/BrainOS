# Async Ingestion Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ingestion asynchronous — submitting returns instantly, a backend-owned thread-pool drains a job queue in parallel with real per-stage progress, streamed over SSE to the existing `QueueDock`.

**Architecture:** A new in-memory job system in the Mnemosyne FastAPI backend (`mnemosyne/jobs/`) sits in front of the unchanged synchronous `MnemosyneService.ingest`. Browsers enqueue via `POST /api/jobs/ingest`; a `ThreadPoolExecutor` runs jobs; an SSE endpoint streams `snapshot` events. The existing Next proxy routes (`/api/jobs*`) and the existing `QueueDock` component light up once the backend implements the contract; the dock is extended to show multiple parallel active jobs.

**Tech Stack:** Python 3.13 · FastAPI · `concurrent.futures.ThreadPoolExecutor` · pytest · Next.js 16 / React 19 · TypeScript · SSE (`EventSource`).

**Spec:** `docs/superpowers/specs/2026-06-07-async-ingest-queue-design.md`

**Conventions:** Backend tests run from the repo root with `mnemosyne/.venv/bin/python -m pytest`. The job tests use an **injected stub ingest** and need no Neo4j/Qdrant/LLM. Commit after each task.

---

## File Structure

**Backend (new)**
- `mnemosyne/jobs/__init__.py` — package exports.
- `mnemosyne/jobs/models.py` — `Job` dataclass, `make_title`, `now_iso`.
- `mnemosyne/jobs/manager.py` — `JobManager` (queue, worker pool, progress, cancel, snapshot, version).
- `mnemosyne/api/jobs_routes.py` — the `/api/jobs*` FastAPI router.
- `mnemosyne/tests/test_jobs_models.py`, `test_jobs.py`, `test_extraction_progress.py`, `test_jobs_api.py`.

**Backend (modified)**
- `mnemosyne/config.py` — `job_workers`, `job_recent_limit`.
- `mnemosyne/pipeline/extraction.py` — optional `on_progress` (chunk-level).
- `mnemosyne/service.py` — `ingest(..., on_progress=None)`.
- `mnemosyne/api/schemas.py` — `JobIngestRequest`.
- `mnemosyne/api/deps.py` — `get_job_manager` singleton.
- `mnemosyne/api/app.py` — include the jobs router.
- `.env.example` — document the new env vars.

**Frontend (modified)**
- `src/components/queue-dock.tsx` — `active: Job[]`, snapshot-only stream, `mnemosyne:ingested` event.
- `src/components/app-shell.tsx` — mount `<QueueDock />`.
- `src/app/api/ingest/route.ts`, `src/app/api/ingest-file/route.ts` — enqueue, return `{job_id}`.
- `src/app/ingest/page.tsx` — non-blocking submit UX.
- `src/app/page.tsx`, `src/app/graph/page.tsx` — re-fetch on `mnemosyne:ingested`.

---

## Task 1: Config — worker count + history cap

**Files:**
- Modify: `mnemosyne/config.py` (the `Settings` dataclass + the "Causal engine tuning" block)
- Modify: `.env.example`

- [ ] **Step 1: Add the settings fields**

In `mnemosyne/config.py`, add inside the `Settings` dataclass, right after the `# --- Ingestion / large-file chunking ... ---` block (before `# --- Causal engine tuning ---`):

```python
    # --- Async ingestion job queue ---
    job_workers: int = field(default_factory=lambda: _i("JOB_WORKERS", 2))
    job_recent_limit: int = field(default_factory=lambda: _i("JOB_RECENT_LIMIT", 20))
```

- [ ] **Step 2: Document them in `.env.example`**

Append to `.env.example` after the chunking block:

```bash
# ── Async ingestion job queue (optional; defaults shown) ──
# JOB_WORKERS=2          # ingestions processed in parallel
# JOB_RECENT_LIMIT=20    # finished jobs kept in the dock's "recent" history
```

- [ ] **Step 3: Verify it loads**

Run: `mnemosyne/.venv/bin/python -c "from mnemosyne.config import get_settings as g; s=g(); print(s.job_workers, s.job_recent_limit)"`
Expected: `2 20`

- [ ] **Step 4: Commit**

```bash
git add mnemosyne/config.py .env.example
git commit -m "feat(jobs): add JOB_WORKERS and JOB_RECENT_LIMIT settings"
```

---

## Task 2: Job model

**Files:**
- Create: `mnemosyne/jobs/__init__.py`
- Create: `mnemosyne/jobs/models.py`
- Test: `mnemosyne/tests/test_jobs_models.py`

- [ ] **Step 1: Write the failing test**

Create `mnemosyne/tests/test_jobs_models.py`:

```python
from mnemosyne.jobs.models import Job, make_title


def test_make_title_prefers_title_then_source_then_snippet():
    assert make_title("My Title", "src", "some text") == "My Title"
    assert make_title("", "src", "some text") == "src"
    assert make_title("", "", "short event") == "short event"
    assert make_title("", "", "x" * 100) == "x" * 40
    assert make_title("", "", "   ") == "Untitled"


def test_to_public_uses_camelcase_and_hides_payload():
    j = Job(id="1", kind="ingest_text", title="t", text="secret", source_id="s")
    pub = j.to_public()
    assert set(pub) == {
        "id", "kind", "title", "status", "progress",
        "step", "error", "createdAt", "startedAt", "finishedAt",
    }
    assert "text" not in pub
    assert pub["status"] == "queued"
    assert pub["progress"] == 0.0
    assert pub["createdAt"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mnemosyne.jobs'`

- [ ] **Step 3: Create the package + model**

Create `mnemosyne/jobs/__init__.py`:

```python
"""Async ingestion job queue: an in-memory queue + worker pool in front of the
synchronous MnemosyneService.ingest, streamed to the UI's QueueDock over SSE."""

from .manager import JobManager
from .models import Job, make_title, now_iso

__all__ = ["JobManager", "Job", "make_title", "now_iso"]
```

Create `mnemosyne/jobs/models.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add mnemosyne/jobs/__init__.py mnemosyne/jobs/models.py mnemosyne/tests/test_jobs_models.py
git commit -m "feat(jobs): Job model + make_title helper"
```

> Note: `__init__.py` imports `manager` (created in Task 3). If you run other tests before Task 3, this import will fail — that's expected; proceed to Task 3 next.

---

## Task 3: JobManager (queue, parallel workers, progress, cancel)

**Files:**
- Create: `mnemosyne/jobs/manager.py`
- Test: `mnemosyne/tests/test_jobs.py`

- [ ] **Step 1: Write the failing tests**

Create `mnemosyne/tests/test_jobs.py`:

```python
import threading
import time

from mnemosyne.jobs.manager import JobManager


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_enqueue_runs_to_completion():
    seen = {}

    def ingest(text, source_id, on_progress):
        on_progress(0.5, "half")
        seen["text"] = text
        return {"ok": True}

    m = JobManager(ingest, workers=1)
    job = m.enqueue(text="hello", source_id="s", title="t")
    assert _wait(lambda: m.get(job.id).status == "completed")
    j = m.get(job.id)
    assert j.progress == 1.0 and j.step == "Done"
    assert seen["text"] == "hello"


def test_progress_is_reported_to_the_job():
    released = threading.Event()

    def ingest(text, source_id, on_progress):
        on_progress(0.42, "working")
        released.wait(2)

    m = JobManager(ingest, workers=1)
    job = m.enqueue(text="x")
    assert _wait(lambda: m.get(job.id).progress == 0.42)
    assert m.get(job.id).step == "working"
    released.set()


def test_failure_is_captured():
    def ingest(text, source_id, on_progress):
        raise ValueError("boom")

    m = JobManager(ingest, workers=1)
    job = m.enqueue(text="x")
    assert _wait(lambda: m.get(job.id).status == "failed")
    assert "boom" in (m.get(job.id).error or "")


def test_cancel_queued_job_never_runs():
    started = []
    block = threading.Event()

    def ingest(text, source_id, on_progress):
        started.append(text)
        block.wait(2)

    m = JobManager(ingest, workers=1)
    j1 = m.enqueue(text="first")
    assert _wait(lambda: m.get(j1.id).status == "running")
    j2 = m.enqueue(text="second")
    assert _wait(lambda: j2.id in [q["id"] for q in m.snapshot()["queued"]])
    canceled = m.cancel(j2.id)
    assert canceled.status == "canceled"
    block.set()
    assert _wait(lambda: m.get(j1.id).status == "completed")
    assert "second" not in started


def test_two_jobs_run_in_parallel():
    block = threading.Event()

    def ingest(text, source_id, on_progress):
        block.wait(2)

    m = JobManager(ingest, workers=2)
    a = m.enqueue(text="a")
    b = m.enqueue(text="b")
    assert _wait(lambda: len(m.snapshot()["active"]) == 2)
    block.set()
    assert _wait(
        lambda: m.get(a.id).status == "completed" and m.get(b.id).status == "completed"
    )


def test_version_increments_on_change():
    def ingest(text, source_id, on_progress):
        return None

    m = JobManager(ingest, workers=1)
    v0 = m.version()
    job = m.enqueue(text="x")
    assert m.version() > v0
    assert _wait(lambda: m.get(job.id).status == "completed")
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mnemosyne.jobs.manager'`

- [ ] **Step 3: Implement the JobManager**

Create `mnemosyne/jobs/manager.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs.py mnemosyne/tests/test_jobs_models.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add mnemosyne/jobs/manager.py mnemosyne/tests/test_jobs.py
git commit -m "feat(jobs): JobManager with parallel workers, progress, cancel"
```

---

## Task 4: Thread real-stage progress through the pipeline

**Files:**
- Modify: `mnemosyne/pipeline/extraction.py` (`_extract_raw`, `extract_events`)
- Modify: `mnemosyne/service.py` (`MnemosyneService.ingest`)
- Test: `mnemosyne/tests/test_extraction_progress.py`

- [ ] **Step 1: Write the failing test**

Create `mnemosyne/tests/test_extraction_progress.py`:

```python
import dataclasses
from datetime import datetime, timezone

from mnemosyne.config import Settings
from mnemosyne.pipeline.extraction import extract_events


class FakeEmbedder:
    dim = 384

    def embed(self, texts):
        return [[0.0] * self.dim for _ in texts]

    def embed_one(self, text):
        return [0.0] * self.dim


class FakeLLM:
    def extract_events(self, text, reference_time, context=""):
        return [{"summary": f"event:{text[:8]}", "occurred_at": None, "tags": []}]

    def judge_causality(self, cause, effect):
        return {"relation": "caused", "confidence": 0.0, "justification": ""}

    def synthesize(self, query, ordered_chain):
        return ""


def test_chunk_progress_is_reported_monotonically():
    settings = dataclasses.replace(
        Settings(),
        chunk_enabled=True,
        chunk_max_chars=10,
        chunk_size_chars=20,
        chunk_context_chars=0,
        chunk_max_concurrency=1,
    )
    calls: list[tuple[float, str]] = []
    extract_events(
        "A" * 60,
        source_id="x",
        reference_time=datetime.now(timezone.utc),
        llm=FakeLLM(),
        embedder=FakeEmbedder(),
        settings=settings,
        on_progress=lambda f, step: calls.append((f, step)),
    )
    assert calls, "expected at least one progress callback"
    fractions = [f for f, _ in calls]
    assert fractions == sorted(fractions)        # monotonic non-decreasing
    assert fractions[-1] == 1.0
    assert "chunk" in calls[-1][1].lower()


def test_no_callback_is_safe():
    # Small text, no chunking, no on_progress — must not raise.
    extract_events(
        "tiny",
        source_id="x",
        reference_time=datetime.now(timezone.utc),
        llm=FakeLLM(),
        embedder=FakeEmbedder(),
        settings=Settings(),
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_extraction_progress.py -v`
Expected: FAIL — `TypeError: extract_events() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 3: Add `on_progress` to extraction**

In `mnemosyne/pipeline/extraction.py`, replace the `_extract_raw` function with:

```python
def _extract_raw(
    text: str,
    reference_time: datetime,
    llm: LLMClient,
    settings: Settings,
    on_progress=None,
) -> list[dict[str, Any]]:
    """Run the LLM extraction, chunking large inputs with a sliding-context window."""
    if not settings.chunk_enabled or len(text) <= settings.chunk_max_chars:
        result = llm.extract_events(text, reference_time)
        if on_progress:
            on_progress(1.0, "Extracting events")
        return result

    chunks = chunk_text(text, size=settings.chunk_size_chars)
    n = len(chunks)
    ctx_n = max(settings.chunk_context_chars, 0)
    jobs = [
        (ch, (chunks[i - 1][-ctx_n:] if i > 0 and ctx_n else ""))
        for i, ch in enumerate(chunks)
    ]

    def run(job: tuple[str, str]) -> list[dict[str, Any]]:
        chunk, context = job
        return llm.extract_events(chunk, reference_time, context=context)

    raw: list[dict[str, Any]] = []
    done = 0

    def note(result: list[dict[str, Any]]) -> None:
        nonlocal done
        done += 1
        if result:
            raw.extend(result)
        if on_progress:
            on_progress(done / n, f"Extracting events (chunk {done}/{n})")

    workers = max(1, settings.chunk_max_concurrency)
    if workers > 1 and len(jobs) > 1:
        from concurrent.futures import as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run, job) for job in jobs]
            for future in as_completed(futures):
                note(future.result())
    else:
        for job in jobs:
            note(run(job))

    return raw
```

Then replace the `extract_events` signature and its first line. Change the signature to add `on_progress=None`:

```python
def extract_events(
    text: str,
    *,
    source_id: str,
    reference_time: datetime,
    llm: LLMClient,
    embedder: Embedder,
    settings: Settings,
    on_progress=None,
) -> list[Event]:
    raw_events = _extract_raw(text, reference_time, llm, settings, on_progress)
```

(The rest of `extract_events` is unchanged.)

- [ ] **Step 4: Run the extraction test to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_extraction_progress.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Thread `on_progress` into the service**

In `mnemosyne/service.py`, replace the `ingest` method signature and body down to the `return` with:

```python
    def ingest(
        self,
        text: str,
        *,
        source_id: str = "",
        reference_time: Optional[datetime] = None,
        on_progress=None,
    ) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("ingest requires an Anthropic API key for event extraction")

        def report(fraction: float, step: str) -> None:
            if on_progress:
                on_progress(fraction, step)

        ref = reference_time or datetime.now(timezone.utc)
        report(0.05, "Extracting events")
        extracted = extract_events(
            text,
            source_id=source_id,
            reference_time=ref,
            llm=self.llm,
            embedder=self.embedder,
            settings=self.settings,
            # Map extraction's 0..1 onto the 0.05..0.60 band of the whole job.
            on_progress=(lambda f, step: report(0.05 + 0.55 * f, step)) if on_progress else None,
        )

        created: list[Event] = []
        reinforced: list[dict[str, Any]] = []
        edges_created: list[CausalEdge] = []

        report(0.60, "Inferring causal edges")
        total = max(1, len(extracted))
        for idx, ev in enumerate(extracted):
            dup_id = find_duplicate(ev, self.vector, self.graph, self.settings)
            if dup_id is not None:
                count = reinforce(dup_id, self.graph, self.settings, now=ref)
                reinforced.append({"event_id": dup_id, "reinforcement_count": count})
            else:
                self.graph.add_event(ev)
                self.vector.upsert(ev.id, ev.embedding or [], _vector_payload(ev))
                created.append(ev)

                window_start = ev.occurred_at - timedelta(seconds=self.settings.temporal_max_window_s)
                candidates = self.graph.candidate_causes(ev, window_start)
                for edge in infer_edges(ev, candidates, settings=self.settings, llm=self.llm):
                    self.graph.add_edge(edge)
                    edges_created.append(edge)
            report(0.60 + 0.35 * ((idx + 1) / total), "Inferring causal edges")

        report(1.0, "Done")
        return {
            "events_created": [e.id for e in created],
            "events_reinforced": reinforced,
            "edges_created": [_edge_to_dict(e) for e in edges_created],
            "counts": {
                "created": len(created),
                "reinforced": len(reinforced),
                "edges": len(edges_created),
            },
        }
```

- [ ] **Step 6: Verify nothing regressed**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_extraction_progress.py mnemosyne/tests/test_models.py -v`
Expected: PASS. (The full suite needs Neo4j/Qdrant and skips cleanly without them.)

- [ ] **Step 7: Commit**

```bash
git add mnemosyne/pipeline/extraction.py mnemosyne/service.py mnemosyne/tests/test_extraction_progress.py
git commit -m "feat(jobs): optional on_progress reporting through ingest pipeline"
```

---

## Task 5: Backend API — enqueue, snapshot, stream, cancel

**Files:**
- Modify: `mnemosyne/api/schemas.py`
- Modify: `mnemosyne/api/deps.py`
- Create: `mnemosyne/api/jobs_routes.py`
- Modify: `mnemosyne/api/app.py`
- Test: `mnemosyne/tests/test_jobs_api.py`

- [ ] **Step 1: Write the failing test**

Create `mnemosyne/tests/test_jobs_api.py`:

```python
import threading

from fastapi.testclient import TestClient

from mnemosyne.api import deps
from mnemosyne.api.app import app
from mnemosyne.jobs.manager import JobManager


def test_enqueue_then_snapshot_then_cancel():
    block = threading.Event()

    def ingest(text, source_id, on_progress):
        block.wait(1)

    mgr = JobManager(ingest, workers=1)
    app.dependency_overrides[deps.get_job_manager] = lambda: mgr
    try:
        client = TestClient(app)

        r = client.post("/api/jobs/ingest", json={"text": "hello world"})
        assert r.status_code == 200
        jid = r.json()["job_id"]

        snap = client.get("/api/jobs").json()
        ids = [j["id"] for j in snap["active"] + snap["queued"]]
        assert jid in ids

        one = client.get(f"/api/jobs/{jid}")
        assert one.status_code == 200 and one.json()["id"] == jid
    finally:
        block.set()
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs_api.py -v`
Expected: FAIL — `AttributeError: module 'mnemosyne.api.deps' has no attribute 'get_job_manager'`

- [ ] **Step 3: Add the request schema**

Append to `mnemosyne/api/schemas.py`:

```python
class JobIngestRequest(BaseModel):
    text: str = Field(..., min_length=1, description="raw text to ingest asynchronously")
    source_id: str = Field("", description="which document/session this came from")
    title: str = Field("", description="label shown in the queue dock")
    kind: str = Field("ingest_text", description="ingest_text | ingest_file")
```

- [ ] **Step 4: Add the JobManager singleton to deps**

Append to `mnemosyne/api/deps.py`:

```python
from ..jobs.manager import JobManager

_job_manager: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        s = get_settings()

        def ingest_fn(text: str, source_id: str, on_progress) -> object:
            return get_service().ingest(text, source_id=source_id, on_progress=on_progress)

        _job_manager = JobManager(
            ingest_fn, workers=s.job_workers, recent_limit=s.job_recent_limit
        )
    return _job_manager
```

- [ ] **Step 5: Create the router**

Create `mnemosyne/api/jobs_routes.py`:

```python
"""HTTP surface for the async ingestion queue (mounted under /api/jobs).

  POST   /api/jobs/ingest   enqueue text -> {job_id}
  GET    /api/jobs          snapshot {active, queued, recent}
  GET    /api/jobs/stream   SSE: 'snapshot' events on change + heartbeats
  GET    /api/jobs/{id}     one job
  DELETE /api/jobs/{id}     cancel a queued job (no-op for running)
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..jobs.manager import JobManager
from .deps import get_job_manager
from .schemas import JobIngestRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("/ingest")
def enqueue(req: JobIngestRequest, mgr: JobManager = Depends(get_job_manager)):
    job = mgr.enqueue(text=req.text, source_id=req.source_id, title=req.title, kind=req.kind)
    return {"job_id": job.id}


@router.get("")
def snapshot(mgr: JobManager = Depends(get_job_manager)):
    return mgr.snapshot()


@router.get("/stream")
async def stream(request: Request, mgr: JobManager = Depends(get_job_manager)):
    def frame() -> str:
        return f"data: {json.dumps({'event': 'snapshot', 'snapshot': mgr.snapshot()})}\n\n"

    async def gen():
        yield frame()
        last = mgr.version()
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            version = mgr.version()
            if version != last:
                last = version
                idle = 0
                yield frame()
            else:
                idle += 1
                if idle >= 30:  # ~15s keep-alive
                    idle = 0
                    yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{job_id}")
def get_job(job_id: str, mgr: JobManager = Depends(get_job_manager)):
    job = mgr.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job.to_public()


@router.delete("/{job_id}")
def cancel_job(job_id: str, mgr: JobManager = Depends(get_job_manager)):
    job = mgr.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job.to_public()
```

- [ ] **Step 6: Mount the router**

In `mnemosyne/api/app.py`, after the `app = FastAPI(...)` line, add:

```python
from .jobs_routes import router as jobs_router

app.include_router(jobs_router)
```

- [ ] **Step 7: Run the API test to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs_api.py -v`
Expected: PASS (1 passed)

- [ ] **Step 8: Run all queue tests together**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs.py mnemosyne/tests/test_jobs_models.py mnemosyne/tests/test_jobs_api.py mnemosyne/tests/test_extraction_progress.py -v`
Expected: PASS (all)

- [ ] **Step 9: Commit**

```bash
git add mnemosyne/api/schemas.py mnemosyne/api/deps.py mnemosyne/api/jobs_routes.py mnemosyne/api/app.py mnemosyne/tests/test_jobs_api.py
git commit -m "feat(jobs): /api/jobs enqueue, snapshot, SSE stream, cancel endpoints"
```

---

## Task 6: Parallel-aware QueueDock + mount it

**Files:**
- Modify: `src/components/queue-dock.tsx` (replace whole file)
- Modify: `src/components/app-shell.tsx`

- [ ] **Step 1: Replace `queue-dock.tsx` with the parallel-aware version**

The change vs. the existing file: `Snapshot.active` becomes `Job[]`; the SSE handler is snapshot-only (the backend emits snapshots); completion fires a decoupled `mnemosyne:ingested` window event instead of the legacy cache-invalidate. Write `src/components/queue-dock.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState, useCallback } from "react";

type JobStatus = "queued" | "running" | "completed" | "failed" | "canceled";
type JobKind = "ingest_text" | "ingest_file" | string;

interface Job {
  id: string;
  kind: JobKind;
  title: string;
  status: JobStatus;
  progress: number; // 0..1
  step: string | null;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

interface Snapshot {
  active: Job[];
  queued: Job[];
  recent: Job[];
}

const KIND_LABEL: Record<string, string> = {
  ingest_text: "text",
  ingest_file: "file",
};

const STATUS_DOT: Record<JobStatus, string> = {
  queued: "bg-zinc-400",
  running: "bg-blue-500 animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  canceled: "bg-zinc-500",
};

const EMPTY: Snapshot = { active: [], queued: [], recent: [] };

export function QueueDock() {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const lastFinishedAt = useRef<string | null>(null);

  // When a job finishes, tell interested pages (home, /graph) to re-fetch.
  // Deduplicated by the newest finishedAt so the same finish never fires twice.
  const notifyFinished = useCallback((snapshot: Snapshot) => {
    const newest = snapshot.recent.find(
      (j) => j.status === "completed" || j.status === "failed",
    );
    const at = newest?.finishedAt ?? null;
    if (!at || at === lastFinishedAt.current) return;
    lastFinishedAt.current = at;
    window.dispatchEvent(new CustomEvent("mnemosyne:ingested"));
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const apply = (data: { event?: string; snapshot?: Snapshot }) => {
      if (data.snapshot) {
        setSnap(data.snapshot);
        notifyFinished(data.snapshot);
      }
    };

    const connect = () => {
      if (cancelled) return;
      es = new EventSource("/api/jobs/stream");
      es.onopen = () => setConnected(true);
      es.onmessage = (ev) => {
        try {
          apply(JSON.parse(ev.data));
        } catch {
          /* ignore heartbeats / malformed frames */
        }
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!cancelled) retryTimer = setTimeout(connect, 3000);
      };
    };

    fetch("/api/jobs", { cache: "no-store" })
      .then((r) => r.json())
      .then((s: Snapshot) => !cancelled && setSnap(s))
      .catch(() => {});

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [notifyFinished]);

  const { active, queued, recent } = snap;
  const idle = active.length === 0 && queued.length === 0;

  const cancel = async (id: string) => {
    try {
      await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    } catch {
      /* best effort */
    }
  };

  // Idle + collapsed → small floating badge.
  if (idle && !open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-50 size-10 rounded-full bg-[var(--card)] border shadow-lg flex items-center justify-center hover:bg-[var(--muted)]/60 transition-colors group"
        title={connected ? "Queue · idle (click for history)" : "Queue · disconnected"}
        aria-label="Open queue"
      >
        <span className={`size-2.5 rounded-full ${connected ? "bg-emerald-500" : "bg-zinc-400"}`} />
        {recent.length > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-[var(--muted)] text-[10px] font-mono leading-none flex items-center justify-center text-[var(--muted-foreground)] group-hover:bg-[var(--accent)]/15 group-hover:text-[var(--accent)] transition-colors">
            {recent.length > 99 ? "99+" : recent.length}
          </span>
        )}
      </button>
    );
  }

  const headerLabel =
    active.length === 1
      ? `Processing · ${KIND_LABEL[active[0].kind] ?? active[0].kind}`
      : active.length > 1
        ? "Processing"
        : queued.length > 0
          ? "Queued"
          : "Queue";
  const headerTitle =
    active.length === 1
      ? active[0].title
      : active.length > 1
        ? `${active.length} running`
        : queued.length > 0
          ? `${queued.length} waiting`
          : "Idle";

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[320px]">
      <div className="rounded-lg border bg-[var(--card)] shadow-lg overflow-hidden">
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-[var(--muted)]/40 transition-colors text-left"
        >
          <span
            className={`size-2 rounded-full shrink-0 ${
              active.length > 0 ? STATUS_DOT.running : connected ? "bg-emerald-500" : "bg-zinc-400"
            }`}
            title={connected ? "live" : "disconnected"}
          />
          <div className="flex-1 min-w-0">
            <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
              {headerLabel}
            </div>
            <div className="text-sm font-medium truncate">{headerTitle}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {queued.length > 0 && (
              <span className="text-[11px] font-mono text-[var(--muted-foreground)]">
                +{queued.length}
              </span>
            )}
            <span className={`text-[var(--muted-foreground)] transition-transform ${open ? "rotate-180" : ""}`}>
              ⌃
            </span>
          </div>
        </button>

        {/* Per-active progress bars, always visible */}
        {active.map((job) => (
          <div key={job.id} className="px-3.5 pb-2">
            {active.length > 1 && (
              <div className="text-[11px] text-[var(--muted-foreground)] truncate mb-1">{job.title}</div>
            )}
            <div className="h-1 rounded-full bg-[var(--muted)] overflow-hidden">
              <div
                className="h-full bg-[var(--accent)] transition-all"
                style={{ width: `${Math.max(4, Math.round(job.progress * 100))}%` }}
              />
            </div>
            {job.step && (
              <div className="mt-1.5 text-[11px] text-[var(--muted-foreground)] truncate">{job.step}</div>
            )}
          </div>
        ))}

        {open && (
          <div className="border-t bg-[var(--background)]/60 max-h-[60vh] overflow-y-auto">
            {queued.length > 0 && (
              <div className="px-3.5 py-2.5">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
                  Queued
                </div>
                <ul className="space-y-1">
                  {queued.map((j, i) => (
                    <li key={j.id} className="flex items-center gap-2 text-xs group">
                      <span className="font-mono text-[10px] text-[var(--muted-foreground)] w-4 text-right">
                        {i + 1}
                      </span>
                      <span className="size-1.5 rounded-full bg-zinc-400 shrink-0" />
                      <span className="flex-1 truncate">{j.title}</span>
                      <span className="text-[10px] text-[var(--muted-foreground)] uppercase tracking-wide">
                        {KIND_LABEL[j.kind] ?? j.kind}
                      </span>
                      <button
                        onClick={() => cancel(j.id)}
                        className="opacity-0 group-hover:opacity-100 text-[10px] text-red-500 hover:underline transition-opacity"
                        aria-label="cancel"
                        title="Cancel"
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {recent.length > 0 && (
              <div className="px-3.5 py-2.5 border-t">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
                  Recent
                </div>
                <ul className="space-y-1">
                  {recent.slice(0, 8).map((j) => (
                    <li key={j.id} className="flex items-center gap-2 text-xs">
                      <span className={`size-1.5 rounded-full shrink-0 ${STATUS_DOT[j.status]}`} />
                      <span className="flex-1 truncate" title={j.error ?? undefined}>
                        {j.title}
                      </span>
                      <span className="text-[10px] text-[var(--muted-foreground)] uppercase tracking-wide">
                        {j.status === "failed" ? "fail" : j.status === "canceled" ? "cancel" : "ok"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {idle && recent.length === 0 && (
              <div className="px-3.5 py-4 text-xs text-[var(--muted-foreground)] text-center">
                No jobs yet. Ingest something to see it here.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Mount the dock in the shell**

In `src/components/app-shell.tsx`, replace the file body with:

```tsx
"use client";

import { Nav } from "@/components/nav";
import { QueueDock } from "@/components/queue-dock";

/**
 * Top-level shell: sidebar nav + main content + the async-ingestion queue dock
 * (bottom-right), which streams job progress from the backend over SSE.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="md:grid md:min-h-screen md:grid-cols-[240px_1fr]">
      <Nav />
      <main className="min-w-0 pb-24">{children}</main>
      <QueueDock />
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/components/queue-dock.tsx src/components/app-shell.tsx
git commit -m "feat(jobs): parallel-aware QueueDock, mounted in the app shell"
```

---

## Task 7: Ingest API routes enqueue instead of blocking

**Files:**
- Modify: `src/app/api/ingest/route.ts`
- Modify: `src/app/api/ingest-file/route.ts`

- [ ] **Step 1: Rewrite `ingest/route.ts` to enqueue**

Replace `src/app/api/ingest/route.ts` with:

```ts
import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";
import { z } from "zod";

export const runtime = "nodejs";

// Enqueue an async ingestion job. Returns immediately with { job_id }; progress
// is streamed to the QueueDock. The legacy {kind,url,model} fields are accepted
// but ignored — only the text and an optional source label matter.
const Body = z.object({
  content: z.string().min(1),
  title: z.string().optional(),
  source_id: z.string().optional(),
  kind: z.string().optional(),
  url: z.string().optional(),
  model: z.string().optional(),
});

export async function POST(req: Request) {
  let body: z.infer<typeof Body>;
  try {
    body = Body.parse(await req.json());
  } catch (e) {
    return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  }

  try {
    const res = await fetch(`${BACKEND_URL}/api/jobs/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: body.content,
        source_id: body.source_id ?? body.title ?? "ui",
        title: body.title ?? "",
        kind: "ingest_text",
      }),
    });
    if (!res.ok) throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    return NextResponse.json(await res.json()); // { job_id }
  } catch (e) {
    console.error("Enqueue error:", e);
    return NextResponse.json({ error: "Enqueue failed", detail: String(e) }, { status: 500 });
  }
}
```

- [ ] **Step 2: Rewrite `ingest-file/route.ts` to enqueue**

In `src/app/api/ingest-file/route.ts`, replace the backend `fetch(...)` block (the `const res = await fetch(\`${BACKEND_URL}/ingest\` ...)` through the `return NextResponse.json(await res.json());`) with:

```ts
    const res = await fetch(`${BACKEND_URL}/api/jobs/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        source_id: title ?? file.name,
        title: title ?? file.name,
        kind: "ingest_file",
      }),
    });
    if (!res.ok) {
      throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    }
    return NextResponse.json(await res.json()); // { job_id }
```

Also change `export const maxDuration = 300;` to `export const maxDuration = 60;` (no long backend wait now — we only read the file and enqueue).

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/api/ingest/route.ts src/app/api/ingest-file/route.ts
git commit -m "feat(jobs): ingest routes enqueue a job and return { job_id }"
```

---

## Task 8: Non-blocking ingest page UX

**Files:**
- Modify: `src/app/ingest/page.tsx`

- [ ] **Step 1: Swap the result state for a queued-confirmation state**

In `src/app/ingest/page.tsx`, change the imports at the top — remove the now-unused result imports:

```tsx
"use client";

import { useState, useRef } from "react";
```

(Delete the `import type { IngestResult } ...` and `import { relationColor } ...` lines.)

Replace the result state line:

```tsx
  const [result, setResult] = useState<IngestResult | null>(null);
```

with:

```tsx
  const [queued, setQueued] = useState<string | null>(null);
```

- [ ] **Step 2: Make `submitText` enqueue and not block**

Replace the `submitText` function body with:

```tsx
  async function submitText(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setQueued(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, source_id: title || undefined }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setQueued(title || "Pasted text");
      setContent("");
      setTitle("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }
```

- [ ] **Step 3: Make `submitFile` enqueue and not block**

In `submitFile`, replace `setResult(null);` (near the top) with `setQueued(null);`, and replace `setResult(j as IngestResult);` with `setQueued(fileTitle || uploadFile.name);`.

- [ ] **Step 4: Replace the result render with a queued banner**

Replace the line `{result && <IngestSummary result={result} />}` with:

```tsx
      {queued && (
        <div className="mt-6 rounded-md border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-4 py-3 text-sm">
          <span className="font-medium">Queued “{queued}”.</span>{" "}
          <span className="text-[var(--muted-foreground)]">
            Track progress in the queue dock (bottom-right ↘). You can add more while it runs.
          </span>
        </div>
      )}
```

- [ ] **Step 5: Delete the now-unused `IngestSummary` component**

Delete the entire `function IngestSummary({ result }: { result: IngestResult }) { ... }` function (it is no longer referenced).

- [ ] **Step 6: Update the submit button labels**

In `SubmitRow`, change the button text and hint from extraction wording to queueing wording:

```tsx
      <button
        type="submit"
        disabled={loading || disabled}
        className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        {loading ? "Queuing…" : "Add to queue"}
      </button>
      {loading && (
        <span className="text-xs text-[var(--muted-foreground)]">Queuing…</span>
      )}
```

- [ ] **Step 7: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors (confirms no dangling `IngestResult` / `relationColor` / `IngestSummary` references).

- [ ] **Step 8: Commit**

```bash
git add src/app/ingest/page.tsx
git commit -m "feat(jobs): non-blocking ingest page — enqueue and confirm"
```

---

## Task 9: Re-fetch graph data when a job finishes

**Files:**
- Modify: `src/app/graph/page.tsx`
- Modify: `src/app/page.tsx`

- [ ] **Step 1: Graph page — extract `load` and listen for the event**

In `src/app/graph/page.tsx`, change the imports to include `useCallback`:

```tsx
import { useCallback, useEffect, useState } from "react";
```

Replace the existing `useEffect(() => { fetch("/api/graph") ... }, []);` block with:

```tsx
  const load = useCallback(() => {
    fetch("/api/graph")
      .then((r) => r.json())
      .then((d: GraphDump) => setData({ events: d.events ?? [], edges: d.edges ?? [] }))
      .catch(() => setData({ events: [], edges: [] }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const onIngested = () => load();
    window.addEventListener("mnemosyne:ingested", onIngested);
    return () => window.removeEventListener("mnemosyne:ingested", onIngested);
  }, [load]);
```

- [ ] **Step 2: Home page — listen for the event**

`src/app/page.tsx` already has a `load` `useCallback` (fetching `/api/graph`) and `import { useCallback, useEffect, useState }`. Replace its mount effect line:

```tsx
  useEffect(() => { load(); }, [load]);
```

with:

```tsx
  useEffect(() => {
    load();
    const onIngested = () => load();
    window.addEventListener("mnemosyne:ingested", onIngested);
    return () => window.removeEventListener("mnemosyne:ingested", onIngested);
  }, [load]);
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/app/graph/page.tsx src/app/page.tsx
git commit -m "feat(jobs): refresh graph/home views when an ingestion finishes"
```

---

## Task 10: Full verification (manual end-to-end)

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend job test suite**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_jobs.py mnemosyne/tests/test_jobs_models.py mnemosyne/tests/test_jobs_api.py mnemosyne/tests/test_extraction_progress.py -v`
Expected: all PASS.

- [ ] **Step 2: Typecheck the whole frontend**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Bring up the stack**

Ensure Neo4j + Qdrant are running (`./scripts/start-stores.sh`), the backend is running (`mnemosyne/run.sh` or the VS Code debugger), and the frontend (`npm run dev`). Confirm `curl -s localhost:8090/api/jobs` returns `{"active":[],"queued":[],"recent":[]}`.

- [ ] **Step 4: Manual end-to-end check**

In the browser at `http://localhost:3000`:
1. Go to `/ingest`, paste a timeline, click **Add to queue** → the form clears and the "Queued" banner appears immediately (no blocking spinner).
2. The bottom-right dock shows the job as **Processing** with a progress bar and stage text (`Extracting events` → `Inferring causal edges` → `Done`).
3. Quickly queue **two more** inputs → up to `JOB_WORKERS` (2) run in parallel (two active bars); the rest show under **Queued**; hover a queued item and cancel it → it moves to **Recent** as `cancel` and never runs.
4. When a job finishes, the `/graph` and home views update without a manual reload.
5. Reload the page mid-run → the dock re-populates from the backend (state survived the reload). Open a second tab → it shows the same queue.
6. Stop Neo4j and ingest once → the job appears then turns **fail** with the error in its row tooltip; the page does not crash.

- [ ] **Step 5: Final commit (if any docs/notes changed)**

```bash
git add -A
git commit -m "test(jobs): verify async ingestion queue end-to-end" --allow-empty
```

---

## Notes for the implementer

- **Run order matters in Task 2:** `mnemosyne/jobs/__init__.py` imports `manager`, which doesn't exist until Task 3. Implement Tasks 2 and 3 back-to-back; don't run the full suite between them.
- **No Neo4j/Qdrant needed** for Tasks 2–5's tests — they use a stub ingest or fakes. The live pipeline is exercised manually in Task 10.
- **`POST /ingest` is untouched** — the existing synchronous endpoint, its tests, and the Postman collection keep working.
- **Route order** in `jobs_routes.py`: `/ingest` and `/stream` are declared before `/{job_id}` so they aren't captured as an id.
