# Vector Space Day SF — Research & Strategy Briefing

**Event:** Vector Space Day SF, 2026-06-11, The Midway
**Speakers/sponsors of note:** LlamaIndex, mem0, Neo4j, Google DeepMind, Qualcomm, Arize, TwelveLabs
**Tracks:** Search & AI Retrieval · Agents & Memory · Edge & Robotics AI

This document captures deep research on (1) harness engineering, (2) the AI agent memory landscape, (3) Graphiti as a framework BrainOS can build on, (4) how BrainOS fits the harness model, (5) a futuristic missing-piece pitch, (6) BrainOS vs Graphiti as layers (not competitors), and (7) the SemanticOS collaboration with Julian.

> **Reframe note (2026-05-24):** Earlier drafts treated Graphiti as a competitor. Per Julian (SemanticOS founder), Graphiti is correctly understood as a **framework** — a library you build *with*, not against. SemanticOS itself uses Graphiti as the ontology layer inside its stack, and BrainOS should consider the same. Sections 3, 6, and 7 reflect this corrected framing.

---

## 1. What is Harness Engineering, and why the shift?

### The one-line definition

> **Agent = Model + Harness**

The **harness is everything around the model except the model itself**: the orchestration loop, the tool layer, context management, long-term memory, verification gates, observability, and guardrails.

Mitchell Hashimoto's canonical operating principle:
> *"Every time you discover an agent has made a mistake, you take the time to engineer a solution so that it can never make that mistake again."*

That "solution" lives in the harness.

### The three-generation evolution

| Era | Unit of control | What you tune |
|---|---|---|
| **Prompt engineering** (2022–2024) | The message | Wording, few-shot examples, chain-of-thought |
| **Context engineering** (2025) | The session | What goes into the window — RAG, tool defs, history |
| **Harness engineering** (2026) | The system | The runtime loop around N inferences |

Rick Hightower's mental model: **the model is the CPU, the harness is the OS.** Context engineering is one *layer* inside the harness — not its replacement.

### Why the shift was forced (the data)

1. **65% of enterprise AI project failures trace back to harness-level data defects** rather than model reasoning (Masood, *AI Control Plane*).
2. **Identical model + identical data + identical prompts → 42% to 78% success rates** purely based on runtime environment quality (Epsilla).
3. **10x cost reduction is achievable from harness changes alone**: $3.00/MTok → $0.30/MTok plus 4x latency drop, *without changing the model* — through prefix stability, semantic caching, and KV-cache locality (Masood).
4. **TerminalBench**: harness changes moved agents **20+ ranking positions** without touching weights (Daily Dose of DS).

### The ETCLOVG canonical taxonomy (7 layers)

| Layer | What it does | Examples |
|---|---|---|
| **E** — Execution loop | Observe → Think → Act, when to stop | Claude Code agent loop, AutoGPT loops |
| **T** — Tool/function calling | Capability surface area | MCP servers, function definitions, logits masking |
| **C** — Context management | Window discipline | Compaction, summarization, prefix-cache stability |
| **L** — Long-term memory/state | Cross-session persistence | Scratchpads, AGENTS.md, todo.md, virtualized memory |
| **O** — Orchestration | Multi-step flow control | Retries, max-step caps, DAG routing, supervisors |
| **V** — Verification | Quality gates | Plan-Execute-Verify, generator-evaluator pairs |
| **G** — Guardrails & observability | Safety + telemetry | Approval gates, secret masking, audit trails, tracing |

### Patterns worth knowing

- **The "Orientation Tax"** — tokens spent because the agent doesn't have a structural map of the environment, leading to "grep-sprees." The fix is **environment engineering**: restructure your repo, docs, and APIs to be *legible* to agents.
- **Plan-Execute-Verify with model layering** ("reasoning sandwich") — expensive reasoning model plans and verifies; cheap model does intermediate work. Becoming the default loop topology.
- **MCP & A2A protocols** — MCP is the "USB-C for AI" vertical agent-to-tool standard; A2A is horizontal delegation across frameworks.

---

## 2. AI Agent Memory Landscape — Market + OSS Scan

The market has split into **four architectural philosophies**, each with a flagship.

### A) Middleware fact-extraction — Mem0

- **Architecture:** Library/SDK between app and vector DB. Every `add()` calls an LLM to extract facts, stores them as discrete entries with user/session/agent scoping.
- **Strengths:** Lowest setup cost, great for personalization chatbots, broadest framework coverage (LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen).
- **Weakness:** LLM call on every write → latency. Graph features paywalled.
- **Benchmark:** LongMemEval 49.0% (GPT-4o).

### B) Temporal knowledge graph — Zep (commercial) / Graphiti (OSS)

- **Architecture:** Full memory **server** with async summarization, entity extraction, and a temporal knowledge graph storing timestamped facts + relationship maps. Understands *state changes*: "I lived in London → moved to Tokyo" becomes a temporally-edged transition.
- **Strengths:** Best for enterprise SaaS where user state evolves. Async write path keeps reads fast.
- **Benchmark:** LongMemEval 63.8% — a **15-point lead over Mem0** driven entirely by the temporal graph.
- **Weakness:** Heavier ops footprint, more concepts.

### C) OS-style self-managed — Letta (formerly MemGPT)

- **Architecture:** Agent itself owns its memory. Core memory (fixed-size, always in context) + archival memory (searchable). LLM uses tool calls to read/write/promote/demote.
- **Strengths:** Genuine autonomy. Agents that run for *days* and curate their own working set.
- **Weakness:** High setup complexity. Latency penalty because the agent itself spends tokens managing memory.

### D) GraphRAG — Cognee

- **Architecture:** Builds a structured knowledge graph from unstructured text. Multi-hop reasoning across documents.
- **Strengths:** Multi-document corpora, deep retrieval over corpus relationships.
- **Weakness:** Specialized; overkill for chat-style personalization.

### Emerging contrarian: Verbatim / no-summarization — MemPalace

- **Insight:** every summarization step is lossy and one LLM-call away from hallucination cascade. Don't summarize, don't extract — just store every conversation in Chroma and retrieve.
- **Benchmark:** Hit **96.6% on LongMemEval** in raw-storage mode.
- **Counter-argument:** storage costs and retrieval slowdown at scale.

### The Tulving taxonomy (LangMem crystallized it)

Production memory systems converge on three types:
- **Episodic** — specific past events ("On 2026-03-12, the user said X")
- **Semantic** — facts and preferences ("user prefers Postgres over MySQL")
- **Procedural** — agent's own learned operating instructions, often as self-rewriting system prompts

### Benchmarks that matter in 2026

- **LoCoMo** — 1,540 questions, multi-session recall. Top score: **92.5**.
- **LongMemEval** — 500 questions, knowledge updates + temporal + multi-session. Top score: **94.4**.
- **BEAM** — 1M to 10M token production scale. **Performance drops ~25% from 1M (64.1) to 10M (48.6)** — the field has a *scale wall*.

### The six unsolved problems (Mem0's own 2026 report)

1. **Temporal abstraction at scale** — degrades 25% between 1M → 10M token corpora
2. **Cross-session structure** — systems treat change as *replacement* rather than *evolution*
3. **Application-level eval** — benchmarks don't predict domain workload performance
4. **Privacy architecture** — no standard for consent / retention / deletion
5. **Cross-session identity** — assumes stable `user_id`; breaks on multi-device / anonymous
6. **Memory staleness** — high-relevance memories become *confidently wrong* after circumstances change

### Two deeper gaps nobody is shipping

- **"Half-solved problem" (Moses Njau)** — current systems store *what happened*, not *what was learned from what happened*. Diary entries, not notebook insights. Example: a log says "increased pool 10→20, CPU went up 15%, timeout unresolved" — but the *lesson* "increasing pool size hurts this service" is what should live in memory.
- **Session amnesia (OSS Insight)** — "Every architecture decision you debated, every bug you traced, every shortcut you explained — gone." No system has demonstrated *longitudinal* value (months, not benchmark runs).

---

## 3. Graphiti deep-dive (the framework, not a competitor)

**Critical context: Graphiti is a *framework* — a library you build with, not a competing product.**

- **Graphiti** = open-source temporal knowledge graph library you self-host (`github.com/getzep/graphiti`)
- **Zep** = a *product* built on Graphiti — adds multi-tenancy, managed infra, dashboards, SLAs
- **SemanticOS** = another product built on Graphiti — uses it as the ontology/schema layer inside their Airbyte → Kafka → Graphiti → Neo4j pipeline (see §7)
- **BrainOS** = currently does *not* use Graphiti, but should consider adopting it as the storage substrate (see §6)

> *"Graphiti is the open-source core engine; Zep adds managed infrastructure, multi-user/conversation management, pre-configured retrieval, dashboards, and enterprise SLAs."*

The clean mental model: **Graphiti is to knowledge graphs what Postgres is to relational data** — infrastructure most serious products end up using. The question for BrainOS is not "Graphiti or us?" but "what do we build *on top of* Graphiti that no one else does?"

### What Graphiti uniquely does

1. **Bi-temporal model** — every edge has *two* time axes: when the event **occurred** (validity window) and when it was **ingested**. Lets you ask "what did we know last Tuesday?" *and* "what was actually true last Tuesday?"
2. **Invalidation, not deletion** — old facts marked invalid with `valid_to`. History preserved.
3. **Episodes as provenance unit** — raw ingested chunks are first-class nodes linked to every extracted fact.
4. **Hybrid retrieval** — semantic embeddings + BM25 + graph traversal.
5. **Real-time incremental** — no batch recompute on update; entities resolve immediately against existing nodes.
6. **Multi-backend** — Neo4j (default), FalkorDB, Kuzu (embedded), Amazon Neptune.
7. **Pydantic ontology** — custom entity/edge types as typed Python classes.
8. **Peer-reviewed** — arXiv 2501.13956, ICLR 2026 MemAgents Workshop.

### Cross-system comparison

| | Mem0 | Letta | Cognee | MemPalace | **Graphiti** |
|---|---|---|---|---|---|
| Storage shape | Vector entries | Tiered (core+archival) | GraphRAG | Verbatim vector | **Real graph DB** |
| Temporal model | timestamp field | None first-class | Limited | None | **Bi-temporal w/ validity windows** |
| Fact invalidation | Overwrite | Manual | Limited | N/A | **Soft-invalidate, query history** |
| Update model | Per-add LLM call | Agent-driven | Batch | Append | **Real-time incremental** |
| Backend | Vector DB | DB + buffer | Vector + graph | Chroma | **Neo4j/FalkorDB/Kuzu/Neptune** |
| Provenance | Metadata | Limited | Source links | Raw text | **Episodes as nodes** |

---

## 4. Can BrainOS use harness engineering?

**Yes — and the more interesting framing is that BrainOS is *already partially* a harness for other people's agents, while internally it under-uses harness patterns for itself.**

### What BrainOS already does well (mapped to ETCLOVG)

| Harness layer | BrainOS today | Strength |
|---|---|---|
| **T** — Tools | `brainos_agent/tools.py:1` exposes 10 read/write tools (`ask_brain`, `search_facts`, `lookup_entity`, `get_relationships`, `ingest_text`…) | Strong — this *is* a tool surface for external agents |
| **C** — Context | `SKILLS.md` / `SKILLS.json` is a structured context bundle | Strong — agents load a curated subset, not raw docs |
| **V** — Verification | `FeedbackAgent` audits groundedness, triggers revision when confidence <0.72 | Strong — closes the loop on the *answer*, not the corpus |
| **G** — Guardrails | `_is_sensitive()` blocklist, `EXPORT_TOKEN` gate, `disputed=true` flag | Partial |
| **L** — Long-term memory | `brain.json` + ChromaDB + BM25 + entity index + graph | Strong — but **passive** |

**The thing BrainOS does that the rest of the field doesn't:** it solves the **Orientation Tax**. Most memory systems give the agent raw chunks. BrainOS gives the agent a *legible map* — atomic units, typed entities, directed verbs, confidence scores, temporal status. This is exactly what Masood means by "environment engineering" and it's a real moat.

### Where BrainOS is weak in harness terms

| Harness layer | Gap | Concrete fix |
|---|---|---|
| **E** — Execution loop | The four agents are linear (ingest → struct → exec → feedback). No retry budget, no max-step caps, no escalation policy | Add a runtime ledger: per-job token cap, retry count, escalation to human when FeedbackAgent fails twice |
| **O** — Orchestration | No supervisor over the agents. If `StructuringAgent`'s LLM reconciliation verdict is uncertain, nothing arbitrates | Add a **Supervisor agent** that gets called only when sub-agent confidence < threshold |
| **L** — Memory **for the brain itself** | Brain stores facts about the *company*, but nothing about *its own behavior* — which retrievals worked, which extractions later got reconciled away, which sources keep producing low-confidence units | Add **meta-memory**: a tiny self-graph about which signals/sources/agents performed well per question class |
| **V** — Verification | FeedbackAgent only audits one answer. Nothing audits ingestion ("did this unit prove useful in any answer that scored well?") | Outcome-link units to answers — see §5 |
| **G** — Observability | `_call_log` ring buffer is good. But no eval harness — no "we should have answered X" regression set | Add a **golden Q&A set** auto-extracted from past resolved Slack threads |

### Concrete near-term harness wins for BrainOS (ranked by ROI)

1. **MCP server wrapping `brainos_agent/tools.py`** — turns BrainOS into a first-class tool source for any agent runtime (Claude Code, Cursor, Devin). Tool definitions exist; wrapper is ~200 lines.
2. **Per-source confidence calibration** — `_log_call()` already tracks calls; extend to track which `source_id` led to grounded vs. ungrounded answers. Re-weight retrieval per source.
3. **Plan-Execute-Verify on ingestion**, not just on Q&A — before merging a contested unit, plan the reconciliation, execute the merge in a shadow brain, verify downstream queries don't regress against a golden set.
4. **Budget ledger** — every API route gets a token/call cap with explicit fail-fast.
5. **Agent-readable repo structure for *your customers*** — generate `AGENTS.md`, `ARCHITECTURE.md`, `OWNERS.md` from `brain.json` so any external coding agent can orient in seconds. The Orientation Tax fix as a *product*.

---

## 5. The Missing Piece — Futuristic Pitch (three layers)

Every memory startup is shipping a **better filing cabinet**. The opportunity is to ship **the first brain that has opinions about itself**.

### Idea A — Outcome-Linked Memory (ship this quarter)

**One-line pitch:** RLHF for the knowledge layer, not for the model.

**The gap it closes:** Mem0's #6 (staleness). Njau's "other half" (lessons not events).

**How it works:**
- Every unit gets two new fields: `usefulness_score` (decayed EMA of contributions to grounded answers) and `last_used_at`.
- Every Q&A in `routes/ask.py` emits a closed-loop signal back to `brain.json`: *"unit `u_42` was cited; FeedbackAgent scored answer 0.91 → reward unit `u_42`."*
- ChromaDB scoring boost picks up `usefulness_score` at retrieval time.
- RRF weights become *learned* per question class (`core/indexes.py:71`), not fixed at k=60.
- Units that haven't been used in 90 days AND have `confidence < 0.7` get auto-flagged for the gap analyzer.

**Why defensible:** Static knowledge graphs become *living* knowledge graphs. The longer BrainOS runs, the smarter it gets — which competitors can't claim because they don't have a closed FeedbackAgent loop.

**Implementation footprint:** ~300 lines. Touches `agents/execution.py`, `agents/feedback.py`, `storage/brain.py`, `core/indexes.py`. Two days of work.

### Idea B — The Belief Layer (new SKU)

**One-line pitch:** Beneath facts sits a separate graph of *causal hypotheses* the brain holds with degrees of confidence, actively triangulates, and is willing to retire.

**The gap it closes:** Njau's "other half" *fully* (causal lessons as first-class objects). Mem0's "cross-session structure" (change as evolution).

**Architecture:**

```
              ┌──────────────────────────────────┐
              │   FACTS (brain.json units)        │
              │   "We chose Stripe in Q2 2024"    │
              └─────────────┬────────────────────┘
                            │ async triangulation
                            ▼
              ┌──────────────────────────────────┐
              │   BELIEFS (new beliefs.json)      │
              │   hypothesis: "Stripe is preferred│
              │     for SMB payments because of   │
              │     SCA support"                  │
              │   confidence: 0.74 (Bayesian)     │
              │   support: [u_4, u_19, u_88]      │
              │   contradicts: [u_201]            │
              │   half_life: 180d                 │
              │   last_triangulated: 2026-04-10   │
              └─────────────┬────────────────────┘
                            │ when confidence drops
                            ▼
              ┌──────────────────────────────────┐
              │   ACTIVE QUERIES (Slack DMs)      │
              │   "@alice — I'm seeing 3 cases    │
              │    where pool>20 hurt latency.    │
              │    Pattern or coincidence?"        │
              └──────────────────────────────────┘
```

**Three new agents:**
- **DreamAgent** — runs on idle CPU/GPU cycles. Reads recent units, proposes new beliefs by clustering causal patterns. This is **memory consolidation** — the gap nobody addresses (the literal "sleep" pattern from human cognition).
- **TriangulationAgent** — for each belief, finds independent corroborating sources. A belief supported by N independent sources gets a confidence boost; one supported by N restatements of the same source gets penalized.
- **InquisitorAgent** — when belief confidence drops below threshold, *actively asks humans on Slack to confirm/deny*. Human-in-the-loop active learning at the belief layer, not the fact layer.

**Why it's a category move:** Mem0/Zep/Letta/Cognee/Graphiti are all **passive databases**. A belief layer is the first **epistemic agent** — a memory system that has *opinions about its own knowledge*. The pitch deck line: "Your company brain doesn't just remember — it *suspects, doubts, and learns*."

**What makes it shippable from BrainOS:**
- Existing schema (`confidence`, `evidence`, `disputed`, `validFrom`/`validTo`, `supersededBy`) is *97% there*.
- Add `beliefs.json` with same provenance/temporal/confidence pattern.
- DreamAgent is just a scheduled job hitting the LLM with "here's the diff of new units; what causal patterns do you propose?"

### Idea C — Federated Tacit Memory (12-month bet)

**One-line pitch:** Slack threads are 60% of company knowledge; nobody can share them across companies because of privacy; but the *patterns* in those threads — how teams resolve incidents, which architectural debates produce what outcomes — are universally valuable. Federate the patterns, not the data.

**Why now (market signal):** Interloom raised **$16.5M** in Mar 2026 doing exactly the single-company version of this (calls it a "context graph"). The federated version is unbuilt.

**The mechanic:**
- Each company's BrainOS instance produces **anonymized belief signatures**: "When `kind=ownership` units about `system=payments` were contradicted 3+ times within 30 days, 78% correlated with an upcoming reorg."
- Signatures aggregated across orgs into a **shared belief market** — public-good knowledge layer of "things that tend to be true across companies."
- Local brains query the market for **priors** when their own belief confidence is low.
- Privacy: only typed patterns flow out; never units, never entities, never quotes.

**Why it's futuristic and uncontested:**
- Solves Mem0's gap #4 (privacy architecture) by *requiring* a privacy boundary at the design level.
- It's the **transactive memory** pattern (Wegner 1985) applied across organizations, not within one team.
- No one is doing it because everyone is competing for raw-data possession. Contrarian bet: raw data stays sovereign and *meta-knowledge* federates.

### Ranking for action

1. **For Vector Space Day conversations**: lead with **Idea B (Belief Layer)** — cleanest crystallization of every gap in the field. BrainOS's existing schema is the closest thing in OSS to a belief-ready foundation.
2. **For roadmap**: ship **Idea A (Outcome-Linked Memory)** this quarter — cheap, directly demos the "brain that learns" pitch, sets up data foundation for Idea B.
3. **For fundraising story 12 months out**: **Idea C (Federated Tacit Memory)** — Interloom's raise validates the single-org category; federation is the moat-building move.

---

## 6. BrainOS and Graphiti — Layered, not Competing

> **Framing correction (per Julian, 2026-05-24):** Graphiti is a *framework*, not a competitor. The right question is not "BrainOS vs Graphiti" but "what does BrainOS build *on top of* Graphiti?" This section walks through both the layer-mapping and the practical adoption path.

BrainOS and Graphiti operate at **different layers of the same stack**. They share philosophy (explicit graph, temporal facts, hybrid retrieval, provenance) but split cleanly along a substrate-vs-product line.

### What lives in which layer

```
┌─────────────────────────────────────────────────────┐
│  BrainOS product layer                              │
│  - Typed units (fact/process/decision/ownership/   │
│    policy/gotcha) with confidence + evidence       │
│  - StructuringAgent reconciliation verdicts        │
│    (supersedes/duplicate/conflicts/independent)    │
│  - VLM ingestion (diagrams, whiteboards)           │
│  - FeedbackAgent groundedness audit                │
│  - SKILLS.md export per department                 │
│  - MCP tool surface (brainos_agent/tools.py)       │
│  - Conflict UI, gap analysis, /metrics dashboard   │
└──────────────────────┬──────────────────────────────┘
                       │ writes to / reads from
                       ▼
┌─────────────────────────────────────────────────────┐
│  Graphiti substrate layer                           │
│  - Bi-temporal edges (occurred_at + ingested_at)   │
│  - Soft-invalidation via valid_to                  │
│  - Hybrid retrieval (semantic + BM25 + graph walk) │
│  - Real-time incremental updates                   │
│  - Pydantic ontology for custom node/edge types    │
│  - Neo4j / FalkorDB / Kuzu / Neptune backends      │
└─────────────────────────────────────────────────────┘
```

### What BrainOS gains by adopting Graphiti

| Capability | BrainOS today | After adopting Graphiti |
|---|---|---|
| **Storage** | `brain.json` (file) + ChromaDB + in-memory BM25 | Neo4j/FalkorDB/Kuzu via Graphiti |
| **Scale** | Single-file JSON; degrades past ~100K units | Billions of edges (Neo4j-scale) |
| **Temporal model** | Single-temporal: `validFrom`/`validTo`/`effectiveDate` + `temporalStatus` enum | Bi-temporal: `occurred_at` + `ingested_at` per edge (richer time-travel) |
| **Graph queries** | Python list-filtering | Cypher; PageRank, community detection, shortest-path free |
| **Real-time updates** | Sync ingest, full BM25/entity rebuild | Incremental — entities resolve immediately |
| **Ops surface** | Bespoke (custom indexes, lock files) | Standard graph DB tooling |

### What BrainOS keeps as its own moat (never moves into Graphiti)

These all stay in the BrainOS product layer — they're what makes BrainOS *not just a Graphiti wrapper*:

- **Typed unit kinds** — fact, process, decision, ownership, definition, policy, gotcha. Graphiti has entities + edges; BrainOS adds the *type of knowledge*.
- **Reconciliation verdicts** — `StructuringAgent` calls LLM and classifies as supersedes/duplicate/conflicts/independent. Graphiti only soft-invalidates by time.
- **`disputed` / `conflictsWith` modeling** — explicit conflict surface. Graphiti just stores both edges.
- **VLM multi-modal pipeline** — diagrams, whiteboards, screenshots. Graphiti is text-only.
- **FeedbackAgent groundedness audit** — closed loop on the *answer*. Graphiti has no answer layer.
- **SKILLS.md export** — department-scoped agent-loadable distillation. No Graphiti equivalent.
- **MCP tool surface** — 10 tools designed to be called *by* other agents.
- **End-to-end product** — UI, ingest flows, conflict surfacing, metrics dashboard.

### Strategic implication

**The right move is to adopt Graphiti as the storage substrate and keep everything above intact.** This is exactly what SemanticOS already does (see §7). The pitch becomes:

> "BrainOS is the cognitive layer (typed knowledge, reconciliation, multi-modal, agent intelligence) on top of Graphiti's temporal-graph substrate."

That framing:
- Acknowledges Graphiti as standard infrastructure (not something to out-compete).
- Frees engineering effort away from `brain.json` scaling problems.
- Inherits bi-temporal correctness, scale, and graph algorithms for free.
- Makes interop with SemanticOS trivial (both write into the same kind of substrate).

**Concrete first step:** 1-day spike — write a `storage/graphiti_adapter.py` that mirrors `storage/brain.py`'s API but persists to a local Graphiti+Neo4j instance. Run the existing test suite against it. If the test suite passes, you have your migration path.

---

## 7. SemanticOS — Julian's vision and the collaboration thesis

> **Source:** Julian's "SemanticOS: The Universal Knowledge Operating System" (Sep 2025 YC application doc, shared 2026-05-24). Julian himself flagged the doc is 8 months old and doesn't yet reflect Skills + "other things that now play in our favor."

### What SemanticOS is

**Thesis:** *"Universal Knowledge Operating System"* — a source-agnostic ingestion + graph platform. The bet is that the bottleneck is **getting all the data in**, normalizing it, and exposing a unified graph API.

**The stack (their exact pipeline):**

```
Airbyte (350+ connectors)              ← INPUT: connects to Slack, Notion, GitHub,
    ↓                                     Jira, Google Drive, Gmail, Linear, etc.
Kafka (streaming normalization)        ← Real-time event bus; messages flow through
    ↓                                     as JSON with source metadata
Graphiti (ontology + schema + LLM       ← LLM-powered entity/edge extraction from
   extraction)                            raw text into Pydantic-typed graph nodes
    ↓
Neo4j (persistent knowledge graph)     ← Final storage
    ↓
MCP / API                              ← OUTPUT: agents query the graph
```

**Key claim:** *"connecting 350+ data sources without writing a single line of integration code."* The differentiation is *declarative configuration* — add a new source via config file, not custom code.

### Where the LLM call actually happens (and why this matters)

The LLM call sits **inside Graphiti**, *after* Kafka, *before* Neo4j. It is **not** at the MCP boundary.

```
Airbyte connector reads raw data (e.g. a Slack message JSON)
    ↓
Kafka transports it as a normalized event
    ↓
Graphiti's add_episode() receives the raw text
    ↓
Graphiti calls an LLM (configurable: OpenAI, Anthropic, Gemini) to:
    1. Extract entities (people, services, decisions)
    2. Extract relationships (verbs between entities)
    3. Resolve entities against existing graph nodes
    4. Compute validity windows (occurred_at, ingested_at)
    ↓
Graphiti writes typed nodes/edges into Neo4j
    ↓
MCP exposes the graph for query (read-only from the agent's perspective)
```

**MCP in SemanticOS is the output/query interface, not the ingestion path.** Data comes in via Airbyte connectors; MCP is how agents *read* the resulting graph.

### Honest assessment of SemanticOS's stage (per the Sep 2025 doc)

- ✅ Core architecture deployed and tested
- ✅ 350+ connectors available (Airbyte handles these; not a SemanticOS moat per se — Airbyte is OSS)
- ✅ End-to-end data flow operational
- 🔄 Onboarding 10 design partner customers
- 🔄 Pre-PMF, raising pre-seed / YC application

**Things they don't yet have (in the Sep 2025 doc):**
- No equivalent of BrainOS's typed unit kinds (fact/process/decision/ownership/policy/gotcha)
- No reconciliation verdicts beyond what Graphiti gives for free
- No multi-modal (VLM) ingestion
- No groundedness audit on answers
- No SKILLS export by department (Julian flagged Skills exists *now* but isn't in this doc)

### SemanticOS vs BrainOS — the layer map

These products operate at **different layers of what's actually the same OS**. There is **almost no overlap in the hard engineering work**.

| Layer | SemanticOS | BrainOS |
|---|---|---|
| **Source ingestion** | Airbyte: 350+ connectors via declarative config | Custom: text/PDF/image upload + Slack MCP poller |
| **Streaming normalization** | Kafka pipeline | Sync ingestion handler |
| **Extraction** | Graphiti's LLM extraction (generic entities + edges) | Multi-agent: IngestionAgent with VLM, **typed unit kinds** (fact/process/decision/ownership/policy/gotcha) |
| **Ontology / schema** | Graphiti (bi-temporal edges, Pydantic models) | Custom JSON schema with confidence, evidence, temporal status, supersededBy, conflictsWith |
| **Storage** | Neo4j (via Graphiti) | brain.json + ChromaDB + in-memory BM25 / entity index |
| **Reconciliation** | Graphiti's soft-invalidation | Explicit LLM verdict: supersedes/duplicate/conflicts/independent + `disputed` flag |
| **Answer layer** | "AI-ready API" — agent does the synthesis | ExecutionAgent (5-signal RRF) + FeedbackAgent (groundedness audit + revision) |
| **Agent-shaped output** | MCP for agents to query | MCP tools + SKILLS.md export by department |
| **Stage** | Pre-PMF, raising | (project state; tracked separately) |

### The collaboration thesis (3 models, ranked by leverage)

#### Model A — Full stack integration (highest leverage, highest commitment)

```
SemanticOS layer:                    BrainOS layer:
─────────────────                    ──────────────
Airbyte (350+ sources)               IngestionAgent (VLM + typed extraction)
    ↓                                StructuringAgent (reconciliation verdicts)
Kafka stream                         ExecutionAgent (5-signal retrieval + answer)
    ↓                                FeedbackAgent (groundedness audit)
[hand-off]  ───────────────→         SKILLS.md export per department
    ↓                                MCP tool surface
Graphiti + Neo4j (storage)   ←────── (BrainOS writes here instead of brain.json)
```

**Mechanics:**
- BrainOS **drops** its custom Slack poller, file upload pipeline, and bespoke connectors. Consumes SemanticOS's normalized Kafka stream instead. Suddenly BrainOS has 350+ sources for free.
- BrainOS **drops** `brain.json` + ChromaDB + in-memory BM25. Writes into Graphiti/Neo4j instead. Suddenly BrainOS scales to billions of edges and gets bi-temporal correctness for free.
- BrainOS **keeps everything that's actually hard and differentiated**: typed unit kinds, reconciliation verdicts, FeedbackAgent, VLM, SKILLS export, agent tool surface, conflict UI.
- SemanticOS **gets the intelligence layer** they don't have. Their "AI-ready API" becomes an actual reasoning system, not just a graph query interface.

**Risk:** brand collision — only one name can live at the top. Don't pretend that question isn't there.

#### Model B — Interop partnership (medium commitment)

Both products stay separate. They publish a clean integration contract:
- SemanticOS exposes its normalized event stream (Kafka topic or MCP).
- BrainOS consumes that stream as a first-class source type, runs its extraction/structuring/feedback pipeline, and emits enriched typed units back via another MCP.
- Customers can buy either product alone, or both for a deeper experience.
- Joint case studies, co-marketing, mutual referrals.

**Risk:** each carries its own GTM; the joint story is harder for customers to grok than "one product."

#### Model C — Co-position only (lightest)

Public alignment, no technical integration:
- Joint blog posts, conference appearances (Vector Space Day is a natural forcing function).
- Both endorse the other for their respective layer ("SemanticOS for connectors and scale, BrainOS for typed knowledge and agent intelligence").
- Useful as a warm-up before deciding on A or B.

### Things to verify with Julian before any deep commitment

1. **What does the current architecture look like?** The Sep 2025 doc is 8 months old; Julian flagged Skills + other additions. Ask for a current diagram.
2. **Is the production pipeline running on real customer data?** "Production-ready" claim deserves polite verification.
3. **What's the contingency if Graphiti's roadmap diverges?** Both stacks would inherit that coupling.
4. **What's the smallest joint demo we can ship in 2 weeks?** Spike before deciding on equity/brand/team.
5. **Where do they sit on YC?** If they applied, when do they hear back? Affects timing on any merge conversation.

### Suggested first reply to Julian

> Julian, thanks for sending this — and for the gentle Graphiti correction, which landed. You're right; I had it framed as a peer rather than a framework, and that was the wrong lens. The clearer picture for me now is that SemanticOS and BrainOS sit at *different layers* of what's actually the same OS — your stack (Airbyte → Kafka → Graphiti → Neo4j → MCP) is the substrate; ours (typed units, reconciliation verdicts, VLM extraction, FeedbackAgent, SKILLS export, agent tools) is the cognitive layer on top.
>
> Two specific questions before we dig in deeper:
>
> 1. **What does your current architecture look like?** Your doc is from Sep 2025 and you mentioned Skills + "other things that now play in our favor" — I'd love to see where you've taken it. We've independently landed on a department-scoped SKILLS.md export and an explicit `gotcha` knowledge kind, and I want to compare.
> 2. **What does an MVP integration look like for you?** If we ran BrainOS's IngestionAgent + StructuringAgent + FeedbackAgent on top of SemanticOS's normalized Kafka stream — writing to Graphiti/Neo4j instead of our own JSON+Chroma — what's the smallest demo that would let us see the joint thing working end-to-end? Happy to spike this from our side.
>
> Worth a working session before the next meeting. Vector Space Day on June 11 might also be a good forcing function if you're going to be there.

---

## Sources

### Harness Engineering
- [Harness engineering for coding agent users — Martin Fowler](https://martinfowler.com/articles/harness-engineering.html)
- [Agent Harness Engineering — The Rise of the AI Control Plane (Masood)](https://medium.com/@adnanmasood/agent-harness-engineering-the-rise-of-the-ai-control-plane-938ead884b1d)
- [The Anatomy of an Agent Harness (Avi Chawla)](https://blog.dailydoseofds.com/p/the-anatomy-of-an-agent-harness)
- [The Third Evolution: Why Harness Engineering Replaced Prompting in 2026 (Epsilla)](https://www.epsilla.com/blogs/harness-engineering-evolution-prompt-context-autonomous-agents)
- [Harness Engineering vs Context Engineering (Hightower)](https://medium.com/@richardhightower/harness-engineering-vs-context-engineering-the-model-is-the-cpu-the-harness-is-the-os-51b28c5bddbb)
- [What Is an Agent Harness? (Firecrawl)](https://www.firecrawl.dev/blog/what-is-an-agent-harness)

### Memory Layer Approaches
- [State of AI Agent Memory 2026 (Mem0)](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Mem0 vs Zep vs Letta vs Cognee 2026 (n1n.ai)](https://explore.n1n.ai/blog/ai-agent-memory-comparison-2026-mem0-zep-letta-cognee-2026-04-23)
- [The Agent Memory Race of 2026 — 5 Repos, 4 Architectures (OSS Insight)](https://ossinsight.io/blog/agent-memory-race-2026)
- [The Memory Problem in AI Agents Is Half Solved (Njau)](https://medium.com/data-unlocked/the-memory-problem-in-ai-agents-is-half-solved-heres-the-other-half-ebbf218ae4d5)
- [Multi-Agent Shared Graph Memory (Neo4j)](https://neo4j.com/nodes-ai/agenda/multi-agent-shared-graph-memory-building-collective-knowledge-for-agents/)
- [Best AI Agent Memory Frameworks 2026 (Atlan)](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)

### Graphiti
- [Graphiti GitHub (getzep/graphiti)](https://github.com/getzep/graphiti)
- [Graphiti: Temporal Knowledge Graphs for Agentic Apps (Zep Blog)](https://blog.getzep.com/graphiti-knowledge-graphs-for-agents/)
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv 2501.13956)](https://arxiv.org/abs/2501.13956)
- [Graphiti: Knowledge Graph Memory for an Agentic World (Neo4j)](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [Graphiti Open Source — Zep](https://www.getzep.com/product/open-source/)

### Market Signal
- [Interloom raises $16.5M for tacit-knowledge context graph (Fortune)](https://fortune.com/2026/03/23/interloom-ai-agents-raises-16-million-venture-funding/)

### SemanticOS (collaboration context)
- [semanticos.io](https://semanticos.io/) — Julian's product site
- Julian's "SemanticOS: The Universal Knowledge Operating System" (Sep 2025 YC application doc, internal — shared 2026-05-24)
- [Airbyte 350+ connectors](https://airbyte.com/connectors) — the ingestion layer SemanticOS uses
- [Apache Kafka](https://kafka.apache.org/) — the streaming layer
