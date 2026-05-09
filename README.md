# BrainOS — Company Brain

The biggest blocker to AI automation inside companies is no longer model
quality, it's domain knowledge. Every company has critical know-how
scattered across people's heads, old email threads, Slack, and support
tickets. AI agents can't operate like that.

**BrainOS** is the missing layer. It pulls knowledge out of every fragmented
source, structures it into atomic units, reconciles it as things change,
and emits an executable skill file that AI agents load directly.

Not search. Not chat-over-docs. A living map of how a company actually works.

Copilots are great for helping you draft documents, analyze data in Excel, or summarize teams meeting, mostly working within the ecosystem and within the specific files.'Company Brain' would be more like a central nervous system for the whole company—constantly processing live data from everywhere, like Slack, emails, and other programs. This creates a real time understanding of everything happening, allowing automation to be more proactive and responsive across the business.

## What it does

1. **Ingest** raw content from Slack threads, emails, support tickets, docs,
   meeting notes, PDFs, and architecture diagrams (image OCR via VLM).
2. **Extract** atomic knowledge units across seven kinds — facts, processes,
   decisions, ownership, definitions, policies, and gotchas — each one
   self-contained, with an evidence quote and a confidence score.
3. **Reconcile** new units against existing ones. When a new ownership or
   policy supersedes an old one, the brain marks the old one stale.
4. **Map** entities (people, teams, systems, products, customers) and the
   relationships between them.
5. **Answer** with a hybrid-RAG pipeline (BM25 lexical + dense vector
   retrieval over both extracted units and raw chunks) and a verifier loop
   that strips unsupported claims before responding.
6. **Export** as `SKILLS.md` — a self-contained department-aware file that
   any AI agent can load to operate inside this company.

## Architecture

BrainOS is two services: a Next.js 16 frontend and a Python FastAPI backend
that talks to a vLLM server hosting Qwen 2.5 on an AMD MI300X.

```
┌─────────────────────────┐         ┌──────────────────────────────────┐
│  Next.js 16 (App Router)│  HTTP   │  FastAPI backend (main.py)       │
│  src/app/ + components/ │ ──────▶ │  src/python_backend/             │
│  /ingest /ask /skills … │  :8081  │  • Multi-agent router            │
└─────────────────────────┘         │  • Hybrid RAG (BM25 + Chroma)    │
                                    │  • brain.json + ChromaDB store   │
                                    └──────────────┬───────────────────┘
                                                   │ vLLM HTTP
                                                   ▼
                                    ┌──────────────────────────────────┐
                                    │  vLLM on AMD MI300X              │
                                    │  • Qwen2.5-32B-Instruct (text)   │
                                    │  • Qwen2.5-VL-7B-Instruct (VLM)  │
                                    │  • optional bge-large embeddings │
                                    └──────────────────────────────────┘
```

### Multi-agent pipeline

The backend routes work across five logical tasks. Each can be pinned to
its own model + endpoint via env vars (`{TASK}_MODEL`, `{TASK}_API_BASE`):

| Task          | Purpose                                                   |
| ------------- | --------------------------------------------------------- |
| `extraction`  | Parse a chunk into structured units / entities / edges    |
| `reconcile`   | Decide if a new unit duplicates / supersedes / conflicts  |
| `execute`     | Generate the user-facing answer from retrieved evidence   |
| `feedback`    | Verifier — flag unsupported claims, trigger answer revise |
| `vlm`         | Describe images as prose for the extractor                |

Default routing sends every task to `MODEL_NAME` on `VLLM_API_BASE`. Heavy
lifts (extraction, execute) can stay on the 32B; lighter audits (reconcile,
feedback) can be pointed at a cheaper 7B on a second endpoint.

### Storage

- **`data/brain.json`** — canonical document: sources, extracted units,
  entities, relationships, raw chunks. Soft-deletes via `stale: true`.
- **`data/chroma_db/`** — ChromaDB vector store with two doc types:
  `unit` (extracted statements) and `raw_chunk` (verbatim source spans).
  Used for both semantic retrieval at `/ask` and similarity lookup during
  reconciliation.

### Hybrid retrieval

`/ask` runs three retrievers in parallel and merges them:

1. Dense vector search over extracted units (ChromaDB).
2. Dense vector search over raw chunks (ChromaDB).
3. BM25 lexical search over both populations.

The execute agent answers with inline citations (`[F1]`, `[C2]`, `[R1]`),
the feedback agent verifies grounding, and a revise step rewrites the
answer if any claim is unsupported.

### Code layout

```
src/
  app/                    Next.js 16 App Router
    page.tsx                dashboard
    ingest/                 paste / upload sources
    ask/                    grounded Q&A with citations
    graph/                  entity map
    skills/                 SKILLS.md preview + download
    metrics/                live ingestion + LLM call stats
    api/                    thin proxies to the FastAPI backend
  components/             shared React UI
  lib/
    types.ts                KnowledgeUnit, Entity, Source, BrainState
    store.ts                JSON store helpers (frontend mirror)
    skills.ts               SKILLS.md formatter
    seed-data.ts            five demo sources
  python_backend/
    main.py                 FastAPI app + routers + agents
    seed_demo_data.py       script to seed the demo company
    requirements.txt
    .env                    backend config (vLLM URLs, model names)
data/
  brain.json              canonical knowledge document
  chroma_db/              ChromaDB persistent store
```

## Setup

You need:

- **Node.js 20+** and **npm** for the frontend.
- **Python 3.10+** for the backend.
- A reachable **vLLM server** with at least one chat-capable model (Qwen2.5
  works well). For image ingestion you also need a VLM endpoint.

### 1. Frontend

```bash
npm install
```

The frontend reads `BRAINOS_API_BASE` (default `http://localhost:8081`) to
locate the Python backend. Set it in `.env.local` if you've moved the
backend off `localhost`.

### 2. Python backend

```bash
cd src/python_backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Copy or create `src/python_backend/.env`:

```
# vLLM endpoint serving the chat model
VLLM_API_BASE=http://<your-vllm-host>:8000/v1
MODEL_NAME=Qwen/Qwen2.5-32B-Instruct

# Vision model (can point at the same vLLM if it serves a multimodal model)
VLM_API_BASE=http://<your-vllm-host>:30000/v1
VLM_MODEL_NAME=Qwen/Qwen2.5-VL-7B-Instruct

# Embeddings — defaults to CPU sentence-transformers (downloads ~90 MB)
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Optional GPU embeddings — start a second vLLM instance:
#   vllm serve BAAI/bge-large-en-v1.5 --task embed --port 8002 --dtype float16
# Then uncomment:
# EMBEDDING_API_BASE=http://<your-vllm-host>:8002/v1
# EMBEDDING_MODEL=BAAI/bge-large-en-v1.5

# Optional per-task overrides — point any agent at a different model/endpoint
# EXTRACTION_MODEL=Qwen/Qwen2.5-32B-Instruct
# RECONCILE_API_BASE=http://gpu2:8000/v1
# RECONCILE_MODEL=Qwen/Qwen2.5-7B-Instruct
```

The backend uses raw HTTP (`httpx`) against vLLM's chat-completions and
embeddings APIs — no OpenAI SDK or API key is required.

## Running

Two processes, two terminals.

```bash
# terminal 1 — Python backend on :8081
cd src/python_backend
source venv/bin/activate
python main.py

# terminal 2 — Next.js frontend on :3000
npm run dev
```

Open http://localhost:3000 and click **Seed with example company** on the
dashboard to load five demo sources (Slack, email, ticket, runbook,
leadership meeting). Then try `/ask` with questions like *"Who owns the
billing service?"* or open `/skills` to download the generated `SKILLS.md`.

### Health check

```bash
curl http://localhost:8081/health
# {"status":"ok","model":"Qwen/Qwen2.5-32B-Instruct","chroma_units":42, ...}
```

### Reset state

```bash
curl -X DELETE http://localhost:8081/api/clear
```

This wipes `data/brain.json` and rebuilds an empty ChromaDB collection.
Required after switching embedding models (vector dimensions change).

## Future goals

- **Native connectors** — Slack, Gmail, Notion, Jira, Linear, Confluence.
  Today everything is paste-in or PDF/image upload.
- **Pluggable model routing** — auto-pick small vs. large based on task
  complexity, with cost/latency telemetry exposed in `/metrics`.
- **Streaming answers** — `/ask` currently waits for the full response;
  switch to SSE so the UI shows partial tokens during long generations.
- **Active-learning feedback** — capture user corrections at `/ask` and
  feed them back as authoritative units (with provenance = "human review").
- **Department-scoped skills** — beyond the current single-file
  `SKILLS.md`, emit one skill bundle per department with per-bundle
  permission scopes for downstream agents.
- **Conflict UI** — when reconciliation surfaces a contradiction, give a
  human reviewer a side-by-side diff and a one-click resolution.
- **Production storage** — swap `brain.json` for Postgres and ChromaDB
  for a managed vector DB once we move past the single-tenant demo.
- **Audit trail** — every unit already tracks `evidence`, `createdAt`,
  `updatedAt`, and supersession chains; surface this as a timeline view.

## Why this matters

Every company in the world will need this layer. The AI tools exist. The
company brain layer does not yet until now.
