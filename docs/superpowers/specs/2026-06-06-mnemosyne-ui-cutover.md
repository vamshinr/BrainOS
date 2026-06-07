# Mnemosyne UI Cutover — Design

**Date:** 2026-06-06
**Status:** approved

Retire the legacy knowledge backend (`src/python_backend`) and make the Next.js UI run
entirely on the new Mnemosyne causal memory engine, with a single root `.env`.

## Decisions
- **Approach A — functional causal cutover** (honest causal UI, not a thin adapter).
- **Orphaned pages: keep but disable** (files stay; their API routes return empty 200s).

## Architecture
The Next.js `/api/*` layer is the single adapter to Mnemosyne. One path:
`browser → nginx → Next.js → Mnemosyne (:8090) → Neo4j/Qdrant`. nginx routes everything to
the frontend (no more `/api`→legacy split).

## Work
1. **Config:** one root `.env` (gitignored) for both Python (Mnemosyne `config.py` loads
   root `.env`) and Next.js (auto-loads). Delete `mnemosyne/.env`, `src/python_backend/.env`;
   ship one root `.env.example`. `BACKEND_URL=http://localhost:8090`.
2. **Rewire 3 routes** to Mnemosyne:
   - `POST /api/ingest` → `POST /ingest` (synchronous; returns events/edges created).
   - `POST /api/ask` → `POST /retrieve` (`{anchor, chain, answer, excluded_distractors, mode}`).
   - `GET /api/state` → `GET /graph` (`{events, edges}`).
   - `ingest-file`: `.txt/.md` only (PDF parsing dropped).
3. **Rework pages** to the causal model: `/ingest` (sync result), `/ask` (causal chain +
   narrative + excluded_distractors + causal⇄associative toggle), `/graph` (events +
   causal edges via reworked `graph-view.tsx`), `/` home dashboard. Remove dead global
   pollers (QueueDock, decision-alert popover) from the layout.
4. **Orphaned routes** (jobs, conflicts, decision-alerts, gaps, skills, onboarding, slack,
   failures) return empty/stub 200s; their page files remain (nav-hidden).
5. **Remove legacy:** delete `src/python_backend/`, root `Dockerfile`, fix `railway.json`,
   `nginx.conf` (→ frontend only), `docker-compose.yml` (drop `backend`, frontend →
   `mnemosyne:8090`).

## Verify
Mnemosyne pytest green → `tsc --noEmit` clean → run Mnemosyne + `npm run dev`, exercise
ingest → ask (causal+associative) → graph end-to-end against the real stack.
