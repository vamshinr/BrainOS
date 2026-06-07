# BrainOS — Mnemosyne

A **causal memory engine** for LLM agents, with a Next.js UI. Instead of returning a bag of
semantically-similar chunks, BrainOS stores **timestamped events** and the directed
**cause → effect edges** between them, then answers “why did X happen?” by walking the causal
graph — back to the root cause, forward to the consequences.

> Honest framing: this is *approximate* causality — temporal precedence + linguistic
> association + an LLM judgment — not true causal inference.

## Stack

- **Backend** — `mnemosyne/`: a FastAPI causal engine on `:8090`. Neo4j (graph) + Qdrant
  (vectors) + sentence-transformers (`all-MiniLM-L6-v2`) + Anthropic **Haiku** (both event
  extraction and causal judgment). Deep dive: [`mnemosyne/README.md`](mnemosyne/README.md).
- **Frontend** — `src/`: a Next.js UI on `:3000`. Its `/api/*` routes are a thin adapter to
  Mnemosyne, so every request flows **browser → Next.js → Mnemosyne → Neo4j/Qdrant**.

## Quick start (native)

One script brings up everything — Neo4j, Qdrant, the backend, and the frontend:

```bash
cp .env.example .env          # then set NEO4J_PASSWORD + ANTHROPIC_API_KEY
./scripts/start.sh            # UI :3000 · API :8090 · Neo4j :7474 · Qdrant :6333
./scripts/stop.sh             # stop everything (data on disk is preserved)
```

`start.sh` is idempotent (skips anything already running), bootstraps the Python venv + npm
deps on first run, and streams logs to `.logs/`.

## Quick start (Docker)

One command brings up the whole stack in containers — no local installs, no Neo4j password
setup:

```bash
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
```

Two images build from this repo: **`Dockerfile.frontend`** (the Next.js UI) and
**`mnemosyne/Dockerfile`** (the backend) — two services, two recipes, no duplication.
`docker-compose.yml` also runs Neo4j, Qdrant, and an nginx proxy.

## Configuration — one file

A single gitignored **`.env`** at the repo root configures *both* the backend (read by
`mnemosyne/config.py`) and the frontend (Next.js auto-loads it). Template: `.env.example`.

| Key | Purpose |
|---|---|
| `NEO4J_URI` · `NEO4J_USER` · `NEO4J_PASSWORD` | Neo4j connection |
| `QDRANT_URL` · `QDRANT_COLLECTION` | Qdrant vector store |
| `ANTHROPIC_API_KEY` | Anthropic key (Haiku) |
| `EXTRACTION_MODEL` · `JUDGMENT_MODEL` | both default to Haiku |
| `BACKEND_URL` | where the frontend reaches Mnemosyne (`http://localhost:8090`) |

## Using it

- **Ingest** (`/ingest`) — paste text or upload a `.txt/.md/.csv/.log/.json` file; events are
  extracted and causal edges inferred synchronously.
- **Ask** (`/ask`) — *causal* mode returns the root-cause chain, a “why” narrative, and the
  keyword-similar **distractors it excluded**; flip to *associative* mode to see the plain
  semantic-search baseline for contrast.
- **Map** (`/graph`) — events on a time axis, linked by cause → effect arcs.
- **Reset** — the home page has a **Reset memory** button that clears Neo4j + Qdrant
  (API: `POST /reset`).

## Backend API

`POST /ingest` · `POST /retrieve` · `GET /graph` · `GET /event/{id}` · `POST /edge` ·
`POST /reset` · `GET /health`. The UI reaches these through the Next.js `/api/*` adapter.

## Tests & debugging

```bash
mnemosyne/.venv/bin/python -m pytest mnemosyne/tests -v   # backend (needs Neo4j + Qdrant)
npx tsc --noEmit                                          # frontend typecheck
```

VS Code: `.vscode/launch.json` ships debug configs for the API (`python -m mnemosyne`) and
the pytest suite.

## Layout

```
mnemosyne/        causal memory engine (FastAPI · Neo4j · Qdrant · Anthropic)
src/app/          Next.js pages + /api adapter routes
src/components/    UI (causal-graph, nav, …)
src/lib/          mnemosyne.ts (types + client), backend.ts (BACKEND_URL)
scripts/          start.sh / stop.sh
docker-compose.yml · Dockerfile.frontend   full stack in containers
docs/             design specs
```
