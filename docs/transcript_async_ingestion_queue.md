# Transcript — Async Ingestion Queue (most in-depth thread)

> **What this is:** a faithful reconstruction of the deepest discussion of the session — the
> design and subagent-driven implementation of the async ingestion queue. It is rebuilt from
> the session context, not a raw log export. The very large embedded artifacts (full spec,
> full plan, and the per-task subagent prompts/code) are represented compactly with pointers
> to the committed files, which hold them verbatim:
> - Spec: [`superpowers/specs/2026-06-07-async-ingest-queue-design.md`](superpowers/specs/2026-06-07-async-ingest-queue-design.md)
> - Plan: [`superpowers/plans/2026-06-07-async-ingest-queue.md`](superpowers/plans/2026-06-07-async-ingest-queue.md)
>
> **Date:** 2026-06-07 · **Branch:** `Release_V2`

---

## Phase 0 — Feature request

**User:**
> we should implement a[n] asynchronous queue that should process each ingestion
> asynchronously so that UI isn't blocked. Like we implemented before add a small queue on
> bottom right that when hovered or clicked should show status along with no of ingestions
> pending and done.

**Assistant:** Treated this as a feature build → invoked the **brainstorming** skill before
any code. Explored the existing infrastructure and reported the key findings:
- Ingestion is **fully synchronous** — `/api/ingest` and `/api/ingest-file` `await
  fetch(BACKEND_URL/ingest)` with `maxDuration: 300`; the browser blocks for the whole
  extract-events + infer-edges pass. *That's why the UI blocks.*
- The `QueueDock` component already exists (`src/components/queue-dock.tsx`) — bottom-right
  idle badge → 320px card, active/queued/recent — **but it's never mounted**, and its data
  source is **dead**: `/api/jobs`, `/api/jobs/stream`, `/api/jobs/[id]` proxy to
  `${BACKEND_URL}/api/jobs*`, endpoints that lived in the removed `python_backend`. So: a
  polished shell with no engine behind it. The task is really "rebuild the queue engine."

---

## Phase 1 — Clarifying questions (3 rounds)

**Assistant (Q):** "When you reload the page or open a second tab while ingestions are
processing, what should the queue do?" — options: *survive reload + sync across tabs* /
*survive reload, single instance* / *per-tab simplest*.
**User (A):** **Survive reload + sync across tabs.** → queue lives in the Mnemosyne backend,
real job queue + SSE.

**Assistant (Q):** two forks — concurrency (*one at a time* / *a few in parallel*) and
progress detail (*real stages* / *running→done*).
**User (A):** **A few in parallel** + **Real stages.**

*(Interleaved here: the user twice asked "doesn't launch.json also start qdrant and neo4j?"
— handled separately by adding `scripts/start-stores.sh` + a `tasks.json` `preLaunchTask`
wired into the "Mnemosyne API (debug)" config; verified the stores came up.)*

**Assistant (Q):** With the pipeline being synchronous/blocking, proposed the worker model —
a **`ThreadPoolExecutor`** of workers running the existing `ingest()` unchanged + a separate
**asyncio SSE** endpoint, so the event loop never blocks — and keeping **`POST /ingest`
synchronous** (tests/Postman/README depend on it), adding the queue as a separate path.
**User (A):**
> i confirm

---

## Phase 2 — Design

**Assistant:** Presented the full design in sections (architecture; backend `mnemosyne/jobs/`
= Job model + JobManager with thread pool + version/pub-sub; endpoints under `/api/jobs`;
optional `on_progress` stage map 0.05→0.60→0.95→1.0; parallel-aware dock with `active:
Job[]`; ingest UX; refresh-on-finish via a `mnemosyne:ingested` event; error handling;
testing). Asked for approval.
**User (A):**
> go ahead

---

## Phase 3 — Spec

**Assistant:** Wrote the spec to `docs/superpowers/specs/2026-06-07-async-ingest-queue-design.md`,
ran the self-review (trimmed a speculative `_result` field — YAGNI; pinned default `kind`;
defined the `title` fallback), and presented it for review, flagging defaults (`JOB_WORKERS=2`,
cancel = queued-only, decoupled refresh event). Asked: any changes, and should I commit?
**User (A):**
> commit it and write the plan

**Assistant:** Committed the spec (`328b7e4`, one file), then invoked the **writing-plans**
skill.

---

## Phase 4 — Plan

**Assistant:** Read the exact signatures (`extract_events`, `service.ingest`, `schemas.py`,
`conftest.py`, `app-shell.tsx`, `ingest/page.tsx`, `graph/page.tsx`) to ground the plan in
real code, then wrote a 10-task TDD plan to
`docs/superpowers/plans/2026-06-07-async-ingest-queue.md`. Self-review pass: full spec
coverage, no placeholders, consistent symbol names; hardened the one soft step (home-page
effect) after reading the file. Committed the plan (`fbe9428`). Offered the two execution
modes.
**User (A):**
> option 1 sub agent driven so we can finish faster

---

## Phase 5 — Subagent-driven execution

**Assistant:** Invoked **subagent-driven-development**. For each task: dispatched a fresh
implementer subagent with the full task text + context, then a spec-compliance review, then a
code-quality review, fixing between. Caught a **plan ordering bug** up front (the `__init__.py`
imported `manager` before Task 3 created it) and split it across Tasks 2/3.

| Task | Commit | Result |
|---|---|---|
| 1 — config (`JOB_WORKERS`, `JOB_RECENT_LIMIT`) | `0ebb90e` | verified inline (full diff visible) |
| 2 — Job model + `make_title` | `781e7fb` | TDD 2 passed; review APPROVED |
| 3 — JobManager (parallel/cancel/progress/version) | `8d4365a` | 8 passed; concurrency review APPROVED (lock discipline, `ingest_fn` outside lock, no deadlock/double-add) |
| 4 — `on_progress` through pipeline | `aaf82d5` | 2 + 5 passed; review APPROVED (existing path unchanged) |
| 5 — `/api/jobs` API (enqueue/snapshot/SSE/cancel) | `6244de7` | 11 passed; review verified route order empirically |
| 6 — parallel-aware QueueDock + mount | `6151494` | `tsc` clean; camelCase keys match `to_public()` |
| 7 — ingest routes enqueue | `fedaac0` | `tsc` clean; file-route validation intact |
| 8 — non-blocking ingest page | `f47dfd9` | `tsc` clean; `IngestSummary` removed, no dangling refs |
| 9 — refresh on `mnemosyne:ingested` | `a9bcb53` | `tsc` clean; listeners cleaned up |

**Final whole-feature review** (`git diff fbe9428..HEAD`): all 6 integration seams APPROVED
(enqueue contract, Job JSON keys, SSE framing, proxy paths, completion event, back-compat).
It flagged **one real bug**: the pre-existing `/api/jobs` proxy returned `active: null` on a
502, which would crash the new `active: Job[]` dock when the backend is down. **Fixed**
(`active: [] ` → commit `2c5b073`).

**Verification:** backend job suite **11 passed**; full backend suite **41 passed, 1 skipped**
(opt-in live-LLM); `tsc --noEmit` clean.

---

## Phase 6 — Finishing the branch

**Assistant:** Invoked **finishing-a-development-branch**. Detected a normal repo on
`Release_V2` (tracks `origin/Release_V2`); since it's the user's own tracked branch, offered
publish/integrate choices (not discard/delete).
**User (A):** **Open PR → main**, and **commit the earlier session work as 2 separate commits.**

**Assistant:** Committed the onboarding non-blocking fix (`ea1d986`) and the VS Code
debug-stores setup (`8c9a654`), excluding the `tsconfig.tsbuildinfo` build artifact. Pushed
`Release_V2`. `gh` wasn't installed, so provided the one-click compare URL
(`.../compare/main...Release_V2?expand=1`) + a ready-to-paste PR title/body, and the session
summary.

---

## Outcome

A backend-owned, in-memory job queue with a thread-pool of parallel workers and real
per-stage progress, streamed over SSE to the (now-mounted, parallel-aware) `QueueDock`;
ingestion enqueues and returns instantly; `POST /ingest` stays synchronous. 10 feature
commits + 1 integration fix on `Release_V2`, all tests green, pushed and PR-ready.
