# Mnemosyne — Causal Memory Engine

A causally-indexed, event-sourced memory substrate for LLM agents. Instead of returning
a bag of semantically-similar chunks, Mnemosyne stores **timestamped events** and the
directed **cause → effect edges** between them, then retrieves by *walking those edges*
(backward to root cause, forward to consequences) to return a time-ordered, noise-free
chain.

> **Honest framing:** this is *approximate* causality — temporal precedence +
> linguistic association + an LLM judgment — **not** true causal inference. That is the
> accepted practical tradeoff; the code says so where it matters.

This is the backend core. The Next.js UI in `src/` runs entirely on it through the
`src/app/api/*` adapter routes (the legacy `src/python_backend` has been removed).

## Architecture

Business logic depends only on Protocol interfaces (`interfaces.py`); the backends are
swappable. Per the build constraint, the graph backend is **Neo4j only** (no NetworkX,
no in-memory stub).

| Concern        | Implementation                                   | Interface     |
|----------------|--------------------------------------------------|---------------|
| Graph store    | Neo4j (`graph/neo4j_store.py`)                   | `GraphStore`  |
| Vector store   | Qdrant (`vectorstore/qdrant_store.py`)           | `VectorStore` |
| Embeddings     | sentence-transformers `all-MiniLM-L6-v2` (384-d) | `Embedder`    |
| LLM            | Anthropic — Haiku (extract + judge)              | `LLMClient`   |

### Pipeline (`pipeline/`)
- **Stage A — `extraction.py`** — LLM extracts discrete timestamped events (resolving
  relative times), each embedded and written to Neo4j + Qdrant. Large inputs are
  optionally chunked with a sliding-context window so the call never overflows or
  truncates (`CHUNK_*` / `EXTRACTION_MAX_TOKENS` env vars; small text stays a single call).
- **Stage B — `causal.py`** — three-signal causal inference:
  `confidence = 0.3·temporal + 0.2·linguistic + 0.5·llm`. Temporal precedence prunes
  candidates cheaply; causality (`cause.occurred_at ≤ effect.occurred_at`) is a hard
  invariant. Edges below `CONFIDENCE_THRESHOLD` (0.55) are stored but excluded from
  default traversal.
- **Stage C — `consolidation.py`** — near-duplicates reinforce an existing event
  (`reinforcement_count`) instead of duplicating; `salience` decays with age unless
  reinforced.
- **Retrieval — `retrieval.py`** — causal (anchor → backward/forward traverse → order →
  synthesize) and a minimal associative baseline for comparison.

## API

| Method | Route          | Purpose                                            |
|--------|----------------|----------------------------------------------------|
| POST   | `/ingest`      | text in → events extracted, edges inferred, stored |
| POST   | `/retrieve`    | query in → causal chain or associative chunks      |
| GET    | `/graph`       | dump nodes + edges (visualization / debugging)     |
| GET    | `/event/{id}`  | inspect a single event + its edges                 |
| POST   | `/edge`        | operator-asserted edge (enforces the invariant)    |
| GET    | `/health`      | liveness                                           |

`/retrieve` in causal mode returns `{anchor_event_id, chain, answer, excluded_distractors}`.
`excluded_distractors` — semantically-similar events that are **not** on any causal path —
is the demonstrable proof that causal traversal ignores keyword-similar noise.

## Setup & run

Config comes from the single root **`.env`** (set `NEO4J_PASSWORD` + `ANTHROPIC_API_KEY`).

- **Whole stack** (Neo4j + Qdrant + this backend + the UI): `./scripts/start.sh` from the
  repo root — see the [root README](../README.md).
- **This backend only** (native): `mnemosyne/run.sh` — bootstraps `mnemosyne/.venv` on first
  use, then serves `:8090`. Expects Neo4j (`bolt://localhost:7687`) + Qdrant
  (`http://localhost:6333`) running; `./setup.sh` (re)checks them.
- **Docker** (whole stack): `docker compose up --build` from the repo root.

## API examples

```bash
# ingest
curl -s localhost:8090/ingest -H 'content-type: application/json' \
  -d '{"text":"At 14:02 the cache TTL was cut to 30s. At 14:19 checkout threw 500s, triggered by the saturated DB pool."}'

# causal retrieval
curl -s localhost:8090/retrieve -H 'content-type: application/json' \
  -d '{"query":"Why did checkout start throwing 500s?","mode":"causal","k":8}'
```

## Tests

Tests run against **real** Neo4j + Qdrant (no stubs), isolated on the `TestEvent` node
label and the `mnemosyne_test` Qdrant collection. They skip cleanly if a backend is
unreachable or `NEO4J_PASSWORD` is unset.

```bash
cd /Users/vamshinagireddy/Downloads/BrainOS
python -m pytest mnemosyne/tests -v            # unit + acceptance (Tests 1–4)
MNEMOSYNE_LLM_TESTS=1 python -m pytest mnemosyne/tests/test_llm_pipeline.py -v   # live Anthropic
```

Coverage maps to the spec's acceptance tests: causal chain + excluded distractors
(Test 1), associative failure mode (Test 2), causality invariant (Test 3), reinforcement
(Test 4), plus per-signal unit tests and an opt-in live extract→infer→retrieve test.
