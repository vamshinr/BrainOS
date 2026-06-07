# Async Ingestion Queue — Design

- **Date:** 2026-06-07
- **Status:** Approved (design); pending implementation plan
- **Component:** Mnemosyne backend (`mnemosyne/`) + Next.js frontend (`src/`)

## 1. Problem

Ingestion is fully synchronous. `src/app/api/ingest/route.ts` and
`src/app/api/ingest-file/route.ts` do `await fetch(${BACKEND_URL}/ingest)` with
`maxDuration: 300`; the browser blocks for the entire extract-events +
infer-edges pass (and, for large files, several chunked LLM calls). The user
cannot do anything else while an ingest runs, and cannot queue multiple inputs.

A polished queue UI already exists — `src/components/queue-dock.tsx` (bottom-right
idle badge → 320px card; active job + progress, queued list with cancel, recent
history) — but it is **never mounted** and its data source is **dead**: the Next
proxy routes `/api/jobs`, `/api/jobs/stream`, `/api/jobs/[id]` forward to
`${BACKEND_URL}/api/jobs*`, endpoints that lived in the removed `python_backend`.
The current Mnemosyne backend implements no jobs API.

## 2. Goals / Non-goals

**Goals**
- Submitting an ingest returns immediately; the UI never blocks.
- A backend-owned job queue processes ingestions, surviving page reloads and
  shared across browser tabs (state lives in the server).
- A few jobs process in **parallel** (configurable worker pool).
- The dock shows **real per-stage progress** (extracting → chunk x/N → inferring
  edges → done) and pending/done counts.
- Reuse the existing `QueueDock` and the existing Next proxy routes.

**Non-goals**
- Persisting the queue across a **backend process restart** (in-memory only).
- Interrupting a job mid-pipeline (only *queued* jobs are cancelable).
- Changing the synchronous `POST /ingest` contract (tests, the Postman
  collection, and README curl examples depend on it — it stays as-is).
- PDF/DOC parsing (unchanged: text inputs only).

## 3. Architecture

```
Ingest page ──POST /api/ingest (Next)──▶ POST /api/jobs/ingest (backend)
                                          └─ JobManager.enqueue() → {job_id} (instant)
                                                   │
                      ThreadPoolExecutor (JOB_WORKERS) ── service.ingest(on_progress=…)
                                                   │  (existing synchronous pipeline)
                                                   ▼
QueueDock ◀─SSE /api/jobs/stream (Next proxy)◀── JobManager publishes a snapshot on change
```

The ingest pipeline is synchronous and blocking (sentence-transformers
embeddings, the Anthropic SDK, the neo4j driver). Running it on FastAPI's
asyncio event loop would block the loop and the SSE stream, so jobs run in a
**thread pool** while a separate **asyncio SSE** coroutine streams updates.

## 4. Backend job system (new package `mnemosyne/jobs/`)

### 4.1 `models.py`
```
JobStatus = queued | running | completed | failed | canceled
JobKind   = "ingest_text" | "ingest_file"

@dataclass
class Job:
    id: str                # nanoid/uuid
    kind: JobKind
    title: str             # source label shown in the dock
    status: JobStatus
    progress: float        # 0..1
    step: str | None       # human-readable current stage
    error: str | None
    created_at: str        # ISO-8601
    started_at: str | None
    finished_at: str | None
    # private (never serialized to the dock):
    _text: str
    _source_id: str
```
A `to_public()` returns exactly the fields the dock consumes (no `_text`).

`title` falls back to the request `title`, else `source_id`, else the first ~40
characters of the text, else `"Untitled"`.

### 4.2 `manager.py` — `JobManager`
Single owner of all job state.

- **State:** `dict[str, Job]` registry + FIFO `deque` of queued ids + a recent
  list (cap `JOB_RECENT_LIMIT`, default 20). All mutations and snapshot
  construction happen under one `threading.Lock`.
- **Workers:** `ThreadPoolExecutor(max_workers=JOB_WORKERS)`. On submit, a worker
  pops the job, sets `running`/`started_at`, calls the injected ingest function
  with an `on_progress(fraction, step)` callback, then sets
  `completed`/`failed` + `finished_at` + `_result`.
- **Ingest function is injected** (constructor dependency), not imported, so
  tests pass a stub — the queue is testable without live LLM/Neo4j.
- **Cancel:** `cancel(id)` flips a *queued* job to `canceled` and removes it from
  the FIFO. A *running* job is not interruptible — cancel is a no-op returning
  the unchanged job.
- **Pub/sub bridge (thread → asyncio):** a monotonically increasing `version`
  counter plus an `asyncio.Event`. Workers call `_publish()` after every state
  change, which bumps `version` and sets the event via
  `loop.call_soon_threadsafe`. The SSE coroutine `await`s the event (with a
  timeout for heartbeats) and emits a fresh snapshot whenever `version` advanced.
  The event loop reference is captured when the SSE endpoint first runs.

### 4.3 Snapshot contract (drives the dock)
```
Snapshot = {
  active: Job[]     # 0..JOB_WORKERS running jobs  (NOTE: list, not single)
  queued: Job[]     # FIFO order
  recent: Job[]     # newest first, capped
}
```
This **changes the dock's current `active: Job | null` to `active: Job[]`** to
support parallel workers (see §6).

### 4.4 Progress reporting
Add an **optional** parameter to the pipeline, default `None` (so the sync
`/ingest` path and all existing tests are unaffected):
```
service.ingest(text, *, source_id, reference_time, on_progress=None)
pipeline.extraction.extract_events(..., on_progress=None)
```
Stage map the worker's callback translates into `Job.progress` / `Job.step`:

| progress | step |
|---|---|
| 0.05 | "Extracting events" |
| 0.05–0.60 | "Extracting events (chunk i/N)" (large files; scaled across chunks) |
| 0.60 | "Inferring causal edges" |
| 0.60–0.95 | per-created-event edge inference (scaled) |
| 1.0 | "Done" |

### 4.5 Config (`config.py`)
- `JOB_WORKERS` (int, default **2**) — parallel worker count.
- `JOB_RECENT_LIMIT` (int, default **20**) — recent-history cap.

Interaction note: each ingest may itself fan out chunk extraction up to
`CHUNK_MAX_CONCURRENCY` (default 4). With `JOB_WORKERS=2`, worst case ≈ 8
concurrent Anthropic calls; default kept modest, raise via env if rate limits allow.

## 5. Endpoints (mounted under `/api/jobs`, matching the existing proxies)

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/jobs/ingest` | body `{text, source_id?, title?, kind?}` → enqueue → `{job_id}` (`kind` defaults to `ingest_text`) |
| GET | `/api/jobs` | current snapshot `{active, queued, recent}` |
| GET | `/api/jobs/stream` | SSE; emits `data: {"event":"snapshot","snapshot":…}\n\n` on change; SSE-comment heartbeats (`:\n\n`) which the dock ignores |
| GET | `/api/jobs/{id}` | one job |
| DELETE | `/api/jobs/{id}` | cancel queued (no-op for running) |

Route order: declare `/api/jobs/ingest` and `/api/jobs/stream` **before**
`/api/jobs/{id}` so FastAPI does not match "ingest"/"stream" as an `id`.

`POST /ingest` is unchanged. The JobManager singleton is wired in
`mnemosyne/api/deps.py` next to the `MnemosyneService`; its ingest function is a
closure that calls `get_service().ingest(..., on_progress=cb)` (so it lazily
reuses the same backends and reports degraded/failed if stores are down).

## 6. Frontend changes

- **`src/components/app-shell.tsx`** — mount `<QueueDock />` (currently never rendered).
- **`src/components/queue-dock.tsx`** — `Snapshot.active: Job | null` → `Job[]`:
  - idle = `active.length === 0 && queued.length === 0`;
  - header shows the single active title when one job runs, else `Processing N`;
  - expanded panel gains an **Active** section (one progress bar + step per
    running job) above Queued and Recent;
  - idle badge, cancel-on-queued, and SSE reconnect logic unchanged.
- **`src/app/api/ingest/route.ts`** — switch from awaiting the full result to
  `POST ${BACKEND_URL}/api/jobs/ingest` → return `{job_id}`.
- **`src/app/api/ingest-file/route.ts`** — still read the file's text
  server-side, then enqueue with `kind:"ingest_file"`, `title:file.name` →
  return `{job_id}`.
- **`src/app/ingest/page.tsx`** — submit returns instantly; show inline
  "Queued ↘ track it in the dock" and clear the form so several inputs can be
  dropped in a row. No blocking spinner / no waiting on results.
- **Refresh-on-finish** — replace the legacy `/api/cache/invalidate` +
  `router.refresh()` in the dock (that targeted the old `brain.json`
  `unstable_cache`) with a decoupled `window.dispatchEvent(new
  CustomEvent("mnemosyne:ingested"))`. The home (`/`) and `/graph` client pages
  add a listener that re-fetches `/api/graph`.

The Next routes `/api/jobs`, `/api/jobs/stream`, `/api/jobs/[id]` are unchanged —
they already proxy to the backend paths above.

## 7. Error handling & concurrency

- **Job failure** (LLM/Neo4j error, stores down): the worker catches the
  exception → `status=failed`, `error=str(exc)`, `finished_at` set. The dock
  shows red "fail" with the message in the row tooltip. Enqueue itself never
  fails because the backend is degraded — the *job* fails with a clear reason.
- **Thread safety:** every registry mutation and snapshot build is under the
  manager lock; the asyncio SSE reader only ever reads snapshots.
- **SSE disconnect:** the dock already retries every 3s and re-syncs from the
  next `snapshot` event.
- **Cancel race:** if a job starts running between the dock showing it as queued
  and the DELETE arriving, cancel is a no-op and the job completes normally.

## 8. Testing

**Backend (pytest, `mnemosyne/tests/`):** drive `JobManager` with an **injected
stub ingest** (no live LLM/Neo4j):
- enqueue → worker runs → `completed`, result captured;
- failure path → `failed` with error;
- cancel a queued job → `canceled`, never runs;
- **two jobs run concurrently** with `JOB_WORKERS=2` (stub blocks on an event to
  prove overlap);
- progress callback is monotonic non-decreasing and ends at 1.0.
One API test: `POST /api/jobs/ingest` → `{job_id}`, then `GET /api/jobs` shows it
in `queued`/`active`. SSE endpoint smoke-tested for one `snapshot` frame.

**Frontend:** `npx tsc --noEmit`; manual dock verification (enqueue several,
watch parallel progress, cancel a queued one, see recent history; reload page
mid-run and confirm state persists from the backend).

## 9. Files touched

**Backend (new):** `mnemosyne/jobs/__init__.py`, `models.py`, `manager.py`;
`mnemosyne/api/jobs_routes.py` (the `/api/jobs*` router).
**Backend (edit):** `api/app.py` (include router), `api/deps.py` (JobManager
singleton + ingest closure), `service.py` + `pipeline/extraction.py` (optional
`on_progress`), `config.py` (`JOB_WORKERS`, `JOB_RECENT_LIMIT`),
`tests/` (new job tests).
**Frontend (edit):** `components/app-shell.tsx`, `components/queue-dock.tsx`,
`app/api/ingest/route.ts`, `app/api/ingest-file/route.ts`, `app/ingest/page.tsx`,
`app/page.tsx` + `app/graph/page.tsx` (ingested-event listener).

## 10. Future work (out of scope)

- Persist jobs across backend restarts (SQLite/JSON) if durability is needed.
- Per-job retry on transient LLM/Neo4j errors.
- A dedicated "active jobs > workers" backpressure signal in the dock.
