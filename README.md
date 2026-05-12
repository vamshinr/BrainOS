<p align="center">
  <img src="public/cover.svg" alt="BrainOS — Company Brain" width="100%" />
</p>

# Company Brain — BrainOS

> **Live demo:** [http://34.171.7.162:3000/](http://129.212.176.117:3000/)
> Backend on AMD MI300X via vLLM. May go offline outside hackathon hours — see the [60-second demo](#the-60-second-demo) and walkthrough video for a guaranteed view.

---

The biggest blocker to AI automation inside companies is no longer model quality — it's **domain knowledge**. Every company has critical know-how scattered across people's heads, old email threads, Slack, support tickets, runbooks, and whiteboards. AI agents can't operate like that.

**Company Brain (BrainOS)** is the missing layer. It pulls knowledge out of every fragmented source, structures it into atomic units, reconciles it as things change, and emits an executable skill file that AI agents load directly.

Not search. Not chat-over-docs. **A living map of how a company actually works.**

> *"The biggest blocker to AI automation of companies is no longer the models. Now the blocker is the domain knowledge. We need a new primitive: a company brain. I think every company in the world is going to need one."*
>
> — **Tom Blomfield, Y Combinator** ([Company Brain RFS](https://www.ycombinator.com/rfs))

---

## What it does

1. **Ingest** raw content from Slack threads, emails, support tickets, docs, meeting notes, PDFs, screenshots, and architecture diagrams — paste it in, upload it, or drop an image. No integrations needed for the demo.
2. **Extract** atomic knowledge units across seven kinds: `fact`, `process`, `decision`, `ownership`, `definition`, `policy`, and `gotcha`. Each unit is self-contained, has an `evidence_quote`, and a `confidence` score.
3. **Reconcile** new units against existing ones. When a new ownership or policy **supersedes** an old one, the brain marks the old one stale. When two sources **conflict** with no temporal cue, both are kept and tagged **Disputed**. Pure duplicates are dropped.
4. **Map** entities (people, teams, systems, products, customers) and the **directed relationships** between them (`owns`, `manages`, `depends-on`, `governs`, `replaces`, `reports-to`, …).
5. **Ask** grounded questions with citations, retrieved-context inspection, and a per-answer groundedness audit.
6. **Export** as `SKILLS.md` — a self-contained file any AI agent (Claude Code, Cursor, OpenAI GPTs, Aider) can load to operate inside this company.

## Why this matters

Every company in the world will need this layer. The AI tools exist. The company-brain layer does not yet — **until now**.

---

## Table of Contents

1. [The live Demo](http://129.212.176.117:3000)
2. [Architecture](#architecture)
3. [The Four Agents](#the-four-agents)
4. [Why It's Not Just Another RAG](#why-its-not-just-another-rag)
5. [Multi-Modal Pipeline](#multi-modal-pipeline)
6. [Why AMD MI300X](#why-amd-mi300x)
7. [Comparison vs. Alternatives](#comparison-vs-alternatives)
8. [Tech Stack](#tech-stack)
9. [Run it](#run-it)
10. [Project Structure](#project-structure)
11. [Feature Tour](#feature-tour)
12. [Roadmap](#roadmap)
13. [Submission & Credits](#submission--credits)

---

## Architecture

```
+-------------------------------------------------------------------------+
|                          USER INPUTS                                    |
|  Text paste . PDF upload . Image / diagram . (future: Slack webhook)    |
+-------------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------------+
|  Next.js 15 (App Router) - Frontend + Proxy                             |
|  /ingest  /ask  /map  /skills  /metrics                                 |
|  ModelPicker . GraphView . DisputedBadge . GapAnalysisButton            |
+-------------------------------------------------------------------------+
                                  |  REST + SSE (planned)
                                  v
+-------------------------------------------------------------------------+
|  Python FastAPI Multi-Agent Backend  (localhost:8081)                   |
|                                                                         |
|   +----------------+   +------------------+   +------------------+      |
|   | IngestionAgent | > | StructuringAgent | > |  ExecutionAgent  |      |
|   |  (text + VLM)  |   | (reconcile +     |   | (hybrid retrieve |      |
|   |   chunk + ext. |   |  graph merge)    |   |  + grounded gen) |      |
|   +----------------+   +------------------+   +------------------+      |
|                                                       |                 |
|                                                       v                 |
|                                              +------------------+       |
|                                              |  FeedbackAgent   |       |
|                                              | (groundedness    |       |
|                                              |  audit, conf.)   |       |
|                                              +------------------+       |
|                                                                         |
|   ModelRouter - per-task routing + per-request override                 |
|   _call_log - live in-memory log of every LLM call (visible in /metrics)|
+-------------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------------+
|  AMD MI300X via vLLM (OpenAI-compatible API)                            |
|  +----------------------+  +--------------------+                       |
|  |  Text LLM (70B-cls)  |  |  Vision LLM (7B)   |                       |
|  |  Llama-3.1 / Qwen    |  |  Qwen-VL / LLaVA   |                       |
|  +----------------------+  +--------------------+                       |
|  Single 192 GB HBM3 GPU - both models co-resident, no swap              |
+-------------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------------+
|  STORAGE                                                                |
|  ChromaDB (HNSW cosine vectors) . brain.json (graph + provenance)       |
|  -> Production: Qdrant + Postgres + S3-compatible object store          |
+-------------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------------+
|  OUTPUTS                                                                |
|  . SKILLS.md  (loadable into Claude Code, Cursor, GPTs, Aider)          |
|  . skills.json (machine-readable for custom agents)                     |
|  . REST API (/api/ask, /api/state, /api/analyze/gaps)                   |
|  . MCP server (planned)                                                 |
+-------------------------------------------------------------------------+
```

---

## The Four Agents

Each agent does *one* thing well. They compose into a self-correcting pipeline.

### 1. IngestionAgent — *raw input → structured candidates*

- **Text path**: chunks long content (3500-char windows, 300-char overlap), runs the extraction LLM per chunk, merges results, deduplicates.
- **VLM path**: an image becomes prose via the vision model on the MI300X (architecture diagrams, whiteboards, screenshots), then flows into the text path.
- Extraction prompt enforces a schema with three buckets: `entities`, `units` (atomic, self-contained, kind-tagged, with `evidence_quote` and `confidence`), and `relationships` (directed verbs from a fixed vocabulary).

### 2. StructuringAgent — *candidates → reconciled graph*

- Embeds units into ChromaDB, then queries for semantically similar existing units.
- For each match, calls a small LLM with one of four verdicts:
  - **`supersedes`** — new info replaces old. *"Bob took over billing"* → marks Alice's unit stale, sets `supersededBy`.
  - **`duplicate`** — drop the new one.
  - **`conflicts`** — both claim to be true with no temporal cue → keep both, tag both `disputed`, store `conflictsWith` pointers.
  - **`independent`** — keep both, no relationship.
- Merges entities with case-insensitive name dedup + alias union.
- Stores directed relationships in `brain.json` with provenance back to the source.

### 3. ExecutionAgent — *question → grounded answer*

- Embeds the query, pulls top-k from ChromaDB.
- Builds a numbered context block of self-contained statements.
- Calls the answer LLM with a system prompt that demands specific names ("never say 'the company'") and refuses when context is insufficient.
- Returns the answer **plus the exact sentences fed to the model** so the UI can show provenance.

### 4. FeedbackAgent — *answer → groundedness audit*

- Second LLM call: *"Is this answer supported by these facts?"*
- Returns `confidence` (0–1), `grounded` (boolean), and a one-sentence rationale.
- The UI shows a green **Grounded** or amber **Ungrounded** badge with the score.

---

## Why It's Not Just Another RAG

| Capability | Vanilla RAG | **BrainOS** |
|---|---|---|
| Returns documents | Yes | Yes |
| Returns atomic facts | No | Yes — `kind`-tagged with confidence |
| Directed knowledge graph | No | Yes — verb-typed edges |
| Reconciles contradictions | No | Yes — `supersedes` / `duplicate` / `conflicts` |
| Detects unresolved disputes | No | Yes — Disputed badge in UI |
| Multi-modal (diagrams, screenshots) | No | Yes — VLM pipeline |
| Provenance + per-fact confidence | No | Yes — every fact links to evidence quote |
| Groundedness audit | No | Yes — second-pass FeedbackAgent |
| Knowledge-gap analysis | No | Yes — orphans, missing owners, open disputes |
| Per-task model routing | No | Yes — env-driven, dashboard-visible |
| Per-request model override | No | Yes — dropdown on /ingest and /ask |
| Compiles to agent skills file | No | Yes — `SKILLS.md` for Claude / GPT / Cursor |
| Self-hostable | Sometimes | Yes — open-source core |

---

## Multi-Modal Pipeline

The MI300X co-resides a vision model and a text model on a single card. Real company knowledge isn't text — it's **architecture diagrams, whiteboard photos, Slack screenshots, dashboards, design files**. BrainOS handles all of it:

```
   Architecture diagram (PNG)                   Slack screenshot
            |                                          |
            v                                          v
   +-----------------+                       +-----------------+
   |   VLM on MI300X |                       |   VLM on MI300X |
   |  (Qwen2.5-VL)   |                       |  (Qwen2.5-VL)   |
   +-----------------+                       +-----------------+
            | "auth-svc calls billing                 | "Bob: I think we
            |  which writes to Stripe..."             |  should retire Adyen…"
            v                                          v
   +-------------------------------------------------------------+
   |           Text LLM extraction on MI300X                     |
   |           (Llama-3.1-70B / Qwen-2.5)                        |
   +-------------------------------------------------------------+
            |                                          |
            v                                          v
   directed graph edges                       atomic decision unit
```

The pitch line: **"Two models. One GPU. One brain."**

---

## Why AMD MI300X

- **192 GB HBM3** — single card runs a 32B text model + a 7B VLM + a dedicated embedding model concurrently. **No model swap, no multi-node orchestration, no inference cold start.** On NVIDIA H100 (80 GB) this requires 3+ GPUs.
- **5.3 TB/s memory bandwidth** — keeps the KV cache hot under multi-tenant load.
- **vLLM-native serving** — OpenAI-compatible `/v1/chat/completions` and `/v1/embeddings` make the rest of the stack provider-agnostic.
- **Real Prometheus metrics** — vLLM exposes `/metrics` natively. BrainOS scrapes it for tok/s, queue depth, KV-cache utilization, and per-call latency. The `/metrics` dashboard makes the GPU's work visible to non-engineers.

---

## Comparison vs. Alternatives

| | Glean | Notion AI | MS Copilot | AGENTiGraph | Graphify | OpenClaw | **BrainOS** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-source ingestion (Slack/docs/images) | partial | – | partial | – | partial (code) | – | **yes** |
| Directed knowledge graph | – | – | partial (tenant) | yes | yes | yes | **yes** |
| Reconciles contradictions | – | – | – | – | – | – | **yes** |
| Disputed flagging | – | – | – | – | – | – | **yes** |
| Multi-modal (VLM) | – | – | yes | – | yes | – | **yes** |
| Provenance + confidence per fact | – | – | yes | – | per-edge | – | **yes** |
| Compiles to portable agent skills file | – | – | – | – | – | – | **yes** |
| Self-hostable open-source | – | – | – | yes | yes | yes | **yes** |
| Vendor-neutral agent output | – | – | – | – | yes (MCP) | – | **yes** |

---

## Tech Stack

**Frontend**
- Next.js 15 (App Router, React 19, Server Components)
- Tailwind CSS, custom design system
- Custom force-directed SVG graph visualization (zoom, pan, fullscreen, click-to-inspect)
- TypeScript end-to-end

**Backend**
- Python 3.11 + FastAPI
- vLLM for OpenAI-compatible LLM + VLM serving
- ChromaDB (PersistentClient, HNSW cosine)
- sentence-transformers (`all-MiniLM-L6-v2` default; swappable to `BAAI/bge-large-en-v1.5` on GPU)
- Pydantic for request schemas
- pypdf for PDF extraction

**Models served on AMD MI300X via vLLM**
- Text: Llama-3.1-70B-Instruct or Qwen-2.5 (configurable per task and per request)
- Vision: Qwen-2.5-VL-7B-Instruct or LLaVA-v1.6-Mistral-7B
- Embedding: optional GPU embedding model (BGE) when `EMBEDDING_API_BASE` is set

**Multi-agent architecture**
- Four specialized agents (Ingestion, Structuring, Execution, Feedback)
- `ModelRouter` for per-task routing
- `_resolve_override` for per-request model selection
- In-memory `_call_log` ring buffer (last 80 calls) surfaced live in `/metrics`

**Storage**
- `data/brain.json` — graph + provenance (mtime-aware caching across processes)
- `data/chroma_db/` — vector index (PersistentClient)
- Production target: Postgres + Qdrant + S3-compatible object store

---

## Run it

### Try it instantly
**Live hosted demo:** [http://129.212.176.117:3000/](http://129.212.176.117:3000/) — running on AMD MI300X via vLLM.

### Run locally

#### Prerequisites
- Node.js 20+
- Python 3.11+
- Access to a vLLM-compatible OpenAI endpoint (AMD MI300X box, or any vLLM/Ollama server)

#### 1. Clone + install
```bash
git clone <repo-url>
cd BrainOS

# Frontend
npm install

# Backend
cd src/python_backend
pip install -r requirements.txt
cd ../..
```

#### 2. Configure (`src/python_backend/.env`)
```env
# Default text + VLM endpoint (vLLM on AMD MI300X)
VLLM_API_BASE=http://<your-mi300x-host>:8000/v1
MODEL_NAME=meta-llama/Llama-3.1-70B-Instruct
VLM_MODEL_NAME=Qwen/Qwen2.5-VL-7B-Instruct

# Optional: per-task model routing (split heavy/light tasks across endpoints)
EXTRACTION_MODEL=meta-llama/Llama-3.1-70B-Instruct
RECONCILE_MODEL=Qwen/Qwen2.5-7B-Instruct
EXECUTE_MODEL=meta-llama/Llama-3.1-70B-Instruct
FEEDBACK_MODEL=Qwen/Qwen2.5-7B-Instruct

# Optional: GPU embedding model (otherwise CPU sentence-transformers)
EMBEDDING_API_BASE=http://<your-mi300x-host>:8002/v1
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5

# Optional: security gates
EXPORT_TOKEN=<random-string>          # gates SKILLS.md export
SENSITIVE_TOPICS=salary,acquisition   # /api/ask refuses queries touching these

# Optional: Slack MCP + Slack Events automation
SLACK_MCP_ACCESS_TOKEN=xoxp-or-mcp-token
SLACK_MCP_APP_ID=A1234567890
SLACK_SIGNING_SECRET=<slack-signing-secret>
SLACK_ALLOWED_CHANNELS=C1234567890,C2345678901
SLACK_BOT_USER_ID=U1234567890
SLACK_AUTO_ANSWER_CHANNELS=C1234567890
SLACK_AUTO_ANSWER_PREFIXES=brainos:,brainos,?
```

Slack slash commands are exposed at `POST /api/slack/slash`, and Slack Events are exposed at
`POST /api/slack/events`. In Slack, point the Event Subscriptions request URL at your public BrainOS
web URL plus `/api/slack/events`, for example `https://<your-domain>/api/slack/events`, and subscribe
to `app_mention` plus `message.channels`. The Next.js route preserves Slack's signature headers and
forwards the raw event body to the Python backend.

Automation behavior is intentionally gated:
- App mentions answer in any channel allowed by `SLACK_ALLOWED_CHANNELS`.
- Normal channel messages only answer in `SLACK_AUTO_ANSWER_CHANNELS`.
- Normal channel messages must start with one of `SLACK_AUTO_ANSWER_PREFIXES`, for example:
  `brainos: What is the VeritasGroup GDPR deadline?`
- Answers are posted back into the same Slack thread with grounded BrainOS citations.

#### 3. Run both processes
```bash
# Terminal 1 — Python backend
cd src/python_backend
uvicorn main:app --host 0.0.0.0 --port 8081

# Terminal 2 — Next.js frontend
npm run dev
```

Open `http://localhost:3000`.

---

## Project Structure

```
BrainOS/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── page.tsx            # Dashboard - recent units, stats, gap analysis
│   │   ├── ingest/             # Text / file / image ingestion UI
│   │   ├── ask/                # Question UI with model picker
│   │   ├── graph/              # Force-directed knowledge graph (zoom/pan/fullscreen)
│   │   ├── skills/             # SKILLS.md export + agent integration recipes
│   │   ├── metrics/            # Live AMD MI300X dashboard + LLM call log
│   │   └── api/                # Next.js API routes (proxy to Python)
│   │
│   ├── components/
│   │   ├── graph-view.tsx          # Force-directed SVG graph
│   │   ├── model-picker.tsx        # Per-request model dropdown
│   │   ├── gap-analysis-button.tsx # Knowledge-gap analyzer trigger
│   │   ├── reset-button.tsx        # Brain wipe with full-reload cache bust
│   │   └── seed-button.tsx         # Seed example company
│   │
│   ├── lib/
│   │   ├── types.ts            # KnowledgeUnit, Entity, Relationship types
│   │   ├── store.ts            # brain.json reader with mtime cache
│   │   ├── skills.ts           # SKILLS.md generator (department-aware)
│   │   └── extractor.ts        # Mock extractor for offline dev
│   │
│   └── python_backend/
│       └── main.py             # FastAPI multi-agent backend (single file)
│
├── data/
│   ├── brain.json              # Single source of truth: graph + provenance
│   └── chroma_db/              # Persistent vector index
│
├── PITCH.md                    # YC pitch document
├── TESTING.md                  # Test scenarios + golden Q&A
└── README.md                   # You are here
```

---

## Feature Tour

### Knowledge graph (`/map`)
- Force-directed layout (synchronous simulation, 320 iterations).
- Zoom (mouse wheel), pan (drag), fit-to-screen, fullscreen.
- Click any node to see all its directed relationships.
- Hover dims unrelated nodes; verb labels fade in on highlighted edges.
- Color-coded by entity kind (person, team, system, product, process, concept, tool, customer).
- Node radius scales with degree.

### Live metrics dashboard (`/metrics`)
- AMD MI300X tok/s sparkline (rolling 30 samples).
- Average end-to-end latency.
- GPU + CPU KV-cache utilization bars.
- Live request log: every LLM call (extraction, reconcile, execute, feedback, vlm) with task, model, latency, prompt + completion tokens.
- Model-routing table: which model handles which task, with `custom`/`shared` badges.

### Per-request model picker
- Dropdown on `/ingest` and `/ask`.
- "Auto (default)" + every model reachable from any configured endpoint.
- VLM-mode picker on the image tab — independent vision model and post-VLM extraction model.

### Knowledge-gap analyzer
- Button on the dashboard.
- Pure graph traversal (no LLM call) — fast, deterministic.
- Reports: `missing_owner`, `undescribed_entity`, `orphan_gotcha`, `open_dispute`.
- Severity-tinted modal with high/medium/low counts.

### Disputed badge
- Pulsing red badge on every contested unit.
- `conflictsWith` array stored on both sides.
- `SKILLS.md` exports disputed units with a warning marker so consuming agents refuse to act on them.

### Security gates
- `EXPORT_TOKEN` env gate on `/api/skills_export` — 401 on mismatch.
- `SENSITIVE_TOPICS` env keyword filter on `/api/ask` — refuses with policy message.

### SKILLS.md export
- Per-department segmentation (Engineering / Legal / HR / Finance / Ops).
- Markdown with `~` low-confidence prefix and `DISPUTED` warning.
- Drop-in compatible with Claude Code `CLAUDE.md`, Cursor `.cursorrules`, OpenAI GPT system prompts.

---

## Roadmap

**Shipped**
- Multi-agent ingestion + reconciliation
- Directed knowledge graph with force-directed visualization
- Multi-modal (text + VLM) pipeline
- Conflict / Disputed detection
- Knowledge-gap analyzer
- Per-task model routing + per-request override
- Live `/metrics` dashboard with call log
- SKILLS.md export
- Basic security gates
- Hosted demo on AMD MI300X

**Next 30 days**
- **MCP server** so any agent can query the brain live (closes Graphify gap).
- **Hybrid retrieval** — dense + BM25 + entity-name + 1-hop graph walk with reciprocal rank fusion.
- **Slack webhook ingestion** with debounce/coalesce queue.
- **Per-user read scope** — basic ACL for department segmentation.
- **Temporal facts** — `validFrom` / `validTo` on every unit.

**Next 90 days**
- **Active-learning loop** — when confidence is low or facts conflict, the brain pings the right person on Slack and learns from their answer.
- **Live ingest streaming** for Notion, GitHub, Linear, Google Drive.
- **Knowledge-decay scheduler** — `gotcha`s expire after 365d, `ownership` after 90d, etc.
- **Cross-source corroboration scoring** — facts confirmed by N sources score higher than singletons.

---

## Submission & Credits

**Built for the AMD AI Hackathon**, May 2026.
Aligned with **[Y Combinator's "Company Brain" RFS](https://www.ycombinator.com/rfs)** by Tom Blomfield.

**Hardware**: AMD MI300X, 192 GB HBM3, single GPU.
**Inference**: vLLM (OpenAI-compatible).
**Models tested**: Llama-3.1-70B-Instruct, Qwen-2.5-7B-Instruct, Qwen-2.5-VL-7B-Instruct, LLaVA-v1.6-Mistral-7B.
**Live demo**: [http://129.212.176.117:3000/](http://129.212.176.117:3000/)

**License**: MIT — see [`LICENSE`](LICENSE).

**Documents**
- [`PITCH.md`](PITCH.md) — YC-style pitch document
- [`TESTING.md`](TESTING.md) — golden Q&A + test scenarios
- [`walkthrough.md`](walkthrough.md) — end-to-end demo script

---

> **The brain wakes up every morning knowing more than it knew yesterday — and tells you exactly what's now in dispute.**
