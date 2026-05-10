# BrainOS — A Living Operating System for Company Knowledge

> **One-line:** The shared, structured memory that lets AI agents actually do work inside a company — by turning Slack, docs, diagrams, and tribal knowledge into a graph of atomic, source-cited, time-aware facts that any agent can load before it acts.

> **Built for the AMD Open Hackathon.** Multi-agent pipeline runs on a single AMD MI300X (192 GB HBM3) — 70B text + 7B vision + embedding model concurrent on one GPU, no model-swap latency.

---

## 1. The Problem

Tom Blomfield (YC) said it best:

> *"The biggest blocker to AI automation of companies is no longer the models — it's the domain knowledge. Every company has critical know-how scattered everywhere... We need a new primitive: a company brain."*

Every company runs on a corpus of knowledge that lives nowhere and everywhere:

- **~60%** of operational knowledge in Slack threads.
- **~15%** in Notion / Confluence pages that go stale within months.
- **~10%** in Google Docs no one reopens.
- **~8%** in Linear / Jira tickets and PR descriptions.
- **~5%** in Loom recordings, meeting transcripts, whiteboard photos.
- The rest — *the most valuable part* — in three engineers' heads.

The cost is enormous and quantifiable:

- **3–6 months** for a new hire to become productive — most of that is context absorption, not skill acquisition.
- **2.5 hours per week per engineer** spent searching for information that exists somewhere (McKinsey).
- When a senior engineer leaves, **~40% of their tribal knowledge evaporates** within 30 days.
- AI agents (Claude Code, Cursor, ChatGPT, Devin) can write code beautifully but don't know your team's conventions, who owns what service, why you chose Stripe over Adyen, or that your webhook handler silently drops on a missing signature header.

**The new bottleneck isn't writing code. It's giving the agent enough context to write the *right* code, route the *right* ticket, or refuse the *wrong* refund.**

---

## 2. Why Existing Solutions Don't Solve This

| Tool | What it does | Why it falls short |
|---|---|---|
| Glean / Coveo | Federated enterprise search | Returns documents, not facts. No graph, no reconciliation, no agent integration. |
| Notion AI | Chat over your Notion | Single-source. Can't see Slack, can't read diagrams, doesn't extract structure. |
| Mem.ai / Reflect | Personal memory | Designed for one user, not a company. |
| Slack AI | Summarizes channels | Surface-level. Doesn't build durable knowledge. |
| Custom RAG over docs | Ad-hoc per team | Vector search over text. No relationships, no superseding, no provenance. |
| Devin / Cursor | Code-aware agents | Brilliant at code, blind to *the company that wrote it*. |

Every existing tool optimizes for *retrieval*. None of them produce a **structured, executable map of how the company actually works** that an AI agent can load before reasoning.

---

## 3. The Insight

Three things became true at the same time, and BrainOS sits at their intersection:

1. **Open-weight LLMs (70B-class) and VLMs (7B-class) are good enough** to extract structured facts and directed relationships from messy real-world inputs — Slack threads, PDFs, whiteboard photos, architecture diagrams.
2. **AI agents now consume "skills files"** — Anthropic Skills, OpenAI Custom GPTs, Cursor `.cursorrules`, Aider conventions. There is finally a stable target format for *agent-shaped knowledge*.
3. **AMD MI300X (192 GB HBM3)** lets a single GPU host a 70B text model + a 7B VLM + a dedicated embedding model concurrently with zero model-swap latency — making real-time multimodal ingestion economically viable.

The wedge: **AI agents need a graph, not a search index.**

---

## 4. What BrainOS Actually Is (and Has Built)

A FastAPI multi-agent orchestrator + a Next.js 15 frontend that ingests every form of company knowledge and produces three artifacts:

1. **`brain.json`** — a directed knowledge graph of entities (people, teams, systems, products, customers, tools), atomic knowledge units (fact, process, decision, ownership, definition, policy, gotcha), and **directed relationships** with explicit verbs (`owns`, `manages`, `governs`, `depends-on`, `replaces`, `reports-to`, `defines`, `uses`, `requires`, `integrates-with`).
2. **ChromaDB collection** — embeds every unit *and* every raw source chunk for hybrid retrieval (cosine HNSW).
3. **`SKILLS.md` / `SKILLS.json`** — agent-loadable distillation, per-department or company-wide. Drops directly into Claude Code's `CLAUDE.md`, OpenAI Custom GPT instructions, or a Cursor rule. *This* is what makes BrainOS load-bearing infrastructure rather than a chatbot.

### Four agents, each doing one thing well

- **IngestionAgent** — reads raw input. VLM (LLaVA-1.6 by default) translates diagrams, whiteboards, and screenshots into rich grounded prose ("A includes B", "A writes to B"). Text LLM extracts entities, atomic units, and directed relationships with strict atomicity rules: one claim per unit, full subject in every statement, evidence quote must be a literal substring of the source. Auto-retries on empty extractions. Chunks at 3,500 chars with 300-char overlap; merges across chunks.
- **StructuringAgent** — embeds units into ChromaDB (cosine HNSW), runs reconciliation (`supersedes` / `duplicate` / `conflicts` / `independent`) so the brain *resolves contradictions* instead of accumulating them, and merges into the graph. Future-dated supersessions are deferred via `pendingSupersedes` so "Bob takes over June 1" ingested in May doesn't kill Alice's *current* ownership.
- **ExecutionAgent** — answers questions via 5-signal hybrid retrieval (vector over units, vector over raw chunks, BM25 over enriched unit text, BM25 over raw chunks, exact-entity index, one-hop graph walk) → weighted reciprocal rank fusion → temporal/confidence/stale rerank → grounded generation with mandatory `[F1]/[R1]/[C1]` citations. Returns the exact source sentences fed to the model so users can trace any claim.
- **FeedbackAgent** — second-pass groundedness audit returning `{confidence, grounded, partial, raw_chunk_only, supporting_context_ids, unsupported_claims, missing_aspects, contradictions}`. **If the audit fails (ungrounded, conf < 0.72, unsupported claims, contradictions) the ExecutionAgent rewrites the answer with the unsupported claims removed and re-evaluates.** Both the original draft and the revised answer are surfaced in the UI.

---

## 5. Why This Isn't Just RAG

Five capabilities that no production RAG system has, all live in code today:

1. **Directed knowledge graph.** Not co-mention. Real verbs (`owns`, `manages`, `depends-on`, `replaces`, `reports-to`, `governs`, `defines`) extracted by the LLM and surfaced as a navigable map. Enables structural queries that vector search literally cannot answer (e.g. "who would I escalate to if Wei Zhang at TerraCore opens a P1?").
2. **Reconciliation as a primitive.** When the brain ingests "Alice owns billing" and later "Bob took over billing," the old fact is marked `stale=true`, gets `supersededBy=<new-id>`, `supersededAt`, `validTo`, and `temporalStatus="historical"`. RAG silently keeps both, then hallucinates a 50/50 answer. We also detect *conflicts* — when two sources both claim to be currently true but disagree — and flag them as `disputed` rather than silently picking one.
3. **Multimodal extraction.** A diagram becomes graph edges. A whiteboard photo becomes process knowledge. An org-chart screenshot becomes ownership facts. The VLM prompt explicitly instructs translation of arrows/containment/labels into declarative sentences before the text extractor runs.
4. **Agent-shaped output.** `SKILLS.md` includes a *Scope* block ("when to use this skill"), an *Agent Rules* block compiled from high-confidence operational units ("Follow process: ...", "Check before acting: ...", "Policy constraint: ..."), the relationship graph as `A --owns--> B`, and a source index. The brain isn't *read* by humans — it's *loaded* by agents before they write a PR.
5. **Provenance, confidence, and time per fact.** Every unit links back to its source quote with a confidence score (1.0 = stated directly → 0.4 = inferred), `validFrom/validTo/effectiveDate/observedAt`, and a `temporalStatus` ∈ {current, future, historical, expired, unknown}. Temporal-aware retrieval boosts current facts for "now" questions and historical facts for "in Q1" questions.

### Plus four things even the pitch deck people don't usually call out

- **Verifier-triggered revision.** Real hallucination guardrail, not a vibe check. When the audit says "ungrounded", the answer is rewritten with unsupported claims removed and re-audited. The UI shows the original draft on demand.
- **Knowledge gap detection.** Deterministic graph scan (no LLM) surfaces `missing_owner` (system/team/product with no `owns` edge), `undescribed_entity` (mentioned but never the subject of a unit), `orphan_gotcha` (gotcha with no sibling process/policy), and `open_dispute`. The brain produces a *punch list* of what your company doesn't know about itself.
- **Per-task model routing.** Extraction, reconcile, execute, feedback, and VLM each have their own `*_MODEL` and `*_API_BASE` env vars. Heavy work on a 70B; cheap audit work on a 7B; vision on a 7B VLM — all colocated on the MI300X. Per-request override is exposed in the UI.
- **Two-tier retrieval.** Extracted units are the first-class citizens; raw source chunks are a graceful fallback. The answer prompt explicitly says "if you rely on a raw chunk, say so" — and the verifier caps confidence at 0.82 for raw-chunk-only answers.

---

## 6. The Architecture (technical credibility)

```
┌───────────── Next.js 15 App Router (RSC + Tailwind v4) ─────────────┐
│  /  Dashboard   /ingest  Text|File|Image    /ask  Query + Verifier │
│  /graph  D3 force layout   /skills  per-dept SKILLS.md   /metrics  │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ Server Components fetch with mtime cache tag
                              ▼
┌──────────── FastAPI multi-agent orchestrator (one process) ─────────┐
│                                                                     │
│  IngestionAgent  ──►  StructuringAgent  ──►  brain.json + Chroma    │
│   (LLM + VLM)         (reconcile,                                   │
│                        supersession,                                │
│                        conflicts)                                   │
│                                                                     │
│  ExecutionAgent  ◄──  ChromaDB + BM25(units) + BM25(chunks) +       │
│   (5-signal hybrid)   entity index + 1-hop graph walk → RRF →       │
│                       temporal/confidence/stale rerank              │
│                                                                     │
│  FeedbackAgent   ──►  ExecutionAgent.revise_answer (if ungrounded)  │
│                                                                     │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ OpenAI-compatible vLLM HTTP
                              ▼
┌──────────────── AMD MI300X · 192 GB HBM3 · vLLM ────────────────────┐
│   Llama-3.1-70B-Instruct-FP8-KV   — extraction + answer generation  │
│   LLaVA-1.6-Mistral-7B            — diagram / whiteboard ingestion  │
│   BAAI/bge-large-en-v1.5          — embeddings (vLLM /v1/embeddings)│
│   Qwen2.5-7B-Instruct (optional)  — reconcile + feedback (cheap)    │
└─────────────────────────────────────────────────────────────────────┘
```

Every layer is open-source, swappable, and self-hostable. No vendor lock-in is part of the pitch — companies can run the brain on their own infra.

---

## 7. Status (what's working today)

**Built and working in the demo:**

- ✅ Multi-agent pipeline (Ingestion / Structuring / Execution / Feedback) end-to-end on AMD MI300X via vLLM HTTP.
- ✅ Multimodal ingestion: text, Slack/email pastes, PDF, DOC, DOCX, TXT, MD, CSV, PNG/JPG (via VLM).
- ✅ Knowledge graph with 10 explicit relationship verbs, exposed in the `/graph` D3 visualization.
- ✅ Reconciliation: `supersedes` / `duplicate` / `conflicts` / `independent` with stale-marking and `temporalStatus` propagation.
- ✅ 5-signal hybrid retrieval with reciprocal rank fusion and temporal/confidence/stale rerank.
- ✅ Verifier-triggered answer revision when groundedness fails.
- ✅ `SKILLS.md` and `SKILLS.json` export, per-department, with Agent Rules block compiled from ≥0.75 confidence units.
- ✅ Knowledge gap analysis (deterministic, no LLM): missing owners, undescribed entities, orphan gotchas, open disputes.
- ✅ Per-task model routing (extraction/reconcile/execute/feedback/vlm) with per-request UI override.
- ✅ Live AMD MI300X metrics panel (vLLM Prometheus: tokens/sec, KV-cache %, queue depth, e2e latency).
- ✅ Sensitive-topic blocklist + export-token gating.
- ✅ Server Components with cache-tag invalidation so external `brain.json` writes are reflected without restart.

**Coming next (months 1–3):**

- **MCP server** so agents (Claude, GPT, Cursor) can pull live brain context instead of reading a frozen `SKILLS.md`.
- **Live ingest streams.** Slack / Notion / GitHub / Linear webhook listeners → continuous extraction. The brain that watches the company while you sleep.
- **Active-learning loop.** When confidence is low, the brain *asks the company* on Slack and learns from the answer.
- **Conflict resolution UI** — disputed units already exist in `brain.json` with `conflictsWith`; need a first-class `/conflicts` page with a one-click "this one wins" resolver.
- **Temporal time-travel queries.** "Who owned billing in Q1 vs Q3?" — already represented in the data, surfaced in retrieval; needs a UI affordance.
- **Embeddings on MI300X via vLLM `/v1/embeddings`** — pluggable today (via `EMBEDDING_API_BASE`); default ships with CPU sentence-transformers for laptop demos.

---

## 8. The Demo (60–90 seconds)

1. **Open `/`.** Empty brain. Click *Seed company*.
2. **Cold ingestion.** Drop in a refund-policy PDF, a security-policy DOCX, and a whiteboard photo. Watch the dashboard tick: sources → entities → units → relationships, with `process`, `policy`, `gotcha`, `ownership` colored badges. Open `/graph` — the network is populating with directed edges (`Alice --owns--> refund-policy`, `refund-policy --executed_via--> Stripe`).
3. **Supersession in action.** Ingest one more Slack message: *"EU customers get automatic 14-day refunds, this overrides the 30-day rule for digital products."* The previous refund-policy unit gets a strikethrough — `temporalStatus: historical`, `validTo: today`. The new one is `current`.
4. **Ask a graph question** (the kind RAG can't answer): *"TerraCore Industries is threatening to churn — what's the exact escalation protocol?"* The answer cites `[F3] Alice Chen` (their CSM), `[F7] enterprise threshold $50k ARR`, `[R2] terracore--csm_assigned-->alice_chen`, `[R5] terracore--exec_escalation-->jordan_blake`. **Grounded** badge, confidence 0.91. Sub-second on MI300X.
5. **Ask a conflict question.** *"Which Pricing API endpoint should I use right now — v1, v2, or v3?"* Answer: "The sources disagree — Bob's email says `/v2/pricing`, Kai's migration doc says `/v3/catalog/pricing`, and `/v1/prices` is deprecated as of last quarter. Current canonical: `/v2/pricing`; `/v3` lands Q3." `[DISPUTED]` badge.
6. **Ask a multimodal question.** *"What does this architecture diagram tell us about who owns the embedding service?"* Answer is grounded against the VLM-extracted `Sam Torres --manages--> amd_cloud` edge.
7. **Click *Run gap analysis*.** Punch list appears: `Meridian Financial has no documented support runbook`, `payments-svc has no documented owner`, `2 open disputes`. *RAG cannot do this.*
8. **Click *Export → SKILLS.md*.** Drop the file into a Claude Code session. Ask Claude to *"open a PR for the Stripe API key rotation."* Claude knows: who to tag (Sam Torres), what runbook to follow (1Password vault `Production-DB`), which gotchas to avoid ("never restart production DB without second-engineer approval"), and which clauses require legal review (Net-60+, SOC2 guarantees, gov't entities).

**5 minutes from cold codebase to an AI agent that knows the company.**

---

## 9. The Defensible Moat

- **Workflow lock-in.** Once the brain feeds an org's AI agents, replacing it means re-extracting and re-validating thousands of facts. Switching cost is steep.
- **Data network effect.** Every correction, supersession, and feedback signal makes the extraction pipeline better — for *that customer*, on *their* idiosyncratic vocabulary.
- **Distribution via agent platforms.** Native integrations with Claude Skills, ChatGPT, Cursor — the brain is the upstream context provider for every agent the company uses.
- **Open-source community.** The skills-file format becomes a standard the way `package.json` or `Dockerfile` did. We don't own the format; we own the best implementation of the format.

---

## 10. Go-to-Market

**Beachhead:** Series-B engineering organizations (50–200 engineers) and ops-heavy D2C / fintech companies using Anthropic Claude / Cursor / Copilot. They feel the pain acutely (onboarding, turnover, agent context, refund/policy drift) and have budget.

**Wedge:** Free open-source self-hosted version (this repo). Paid hosted version with managed connectors (Slack, Notion, GitHub, Linear, Salesforce), SSO, audit logs, MCP server.

**Expansion:** Once the brain is the source of truth for one team's AI agents, it becomes the natural source for *every* team. Sales becomes seat-based and viral within the org.

**Pricing (early):** $20 / employee / month. A 100-person company = $24k ARR. 10 such customers = $240k ARR. Achievable in year one.

---

## 11. Why Now

- **2023:** GPT-4 made retrieval-augmented generation interesting, but the LLMs were too expensive to run extraction at scale.
- **2024:** Open-weight LLMs (Llama 3, Mistral, Qwen) hit "good enough" quality for fact extraction at 1/100th the cost.
- **2025:** Open-weight VLMs (Qwen2.5-VL, LLaVA-1.6) cross the threshold for production diagram and screenshot understanding.
- **2025:** AMD MI300X reaches general availability — 192 GB HBM3 makes co-resident text + vision + embedding models economical.
- **2025:** Anthropic Skills, OpenAI Custom GPTs, Cursor rules — every major agent now consumes a "context file." The plug exists; nothing fills it for company-wide knowledge.
- **2026:** MCP becomes a de-facto standard for live agent context — and the brain is the natural upstream for it.

This window did not exist 18 months ago. It will close in 18 more.

---

## 12. The Ask

Looking for **$1.5M seed** to:

- Hire 2 ML engineers (graph retrieval + extraction quality + active learning).
- Hire 1 full-stack engineer (connectors: Slack, Notion, GitHub, Linear, Salesforce; MCP server).
- Get 5 design-partner companies on the hosted version.
- Reach **$100k ARR within 12 months**.

**Status:** Working multi-agent prototype. Live on AMD MI300X. Demo-ready knowledge graph with directed relationships, supersession, conflict detection, gap analysis, verifier-triggered revision, and per-department `SKILLS.md` export. Ready to onboard the first three design partners next month.

---

## Appendix A — One-paragraph version (for cold emails / Twitter)

> BrainOS turns scattered company knowledge — Slack, docs, diagrams, recordings — into a structured graph that AI agents load before they act. Built on AMD MI300X, four specialized agents extract entities, directed relationships, and atomic facts; reconcile contradictions; surface conflicts; detect knowledge gaps; and compile a `SKILLS.md` consumable by Claude, ChatGPT, and Cursor. Not a search tool. The first operating system for company knowledge in the agent era.

## Appendix B — Comparison table

| | RAG chatbot | Glean | Notion AI | **BrainOS** |
|---|---|---|---|---|
| Returns documents | ✅ | ✅ | ✅ | ✅ |
| Returns atomic facts | ❌ | ❌ | ❌ | ✅ |
| Directed relationship graph (with verbs) | ❌ | ❌ | ❌ | ✅ |
| Reconciles contradictions (`supersedes`) | ❌ | ❌ | ❌ | ✅ |
| Surfaces unresolved conflicts | ❌ | ❌ | ❌ | ✅ |
| Multimodal (diagrams, whiteboards, screenshots) | ❌ | partial | ❌ | ✅ |
| Provenance + confidence + temporal status per fact | ❌ | ❌ | ❌ | ✅ |
| Verifier-triggered hallucination revision | ❌ | ❌ | ❌ | ✅ |
| Knowledge-gap detection | ❌ | ❌ | ❌ | ✅ |
| Compiles to agent skills file (Claude / GPT / Cursor) | ❌ | ❌ | ❌ | ✅ |
| Self-hostable | ❌ | ❌ | ❌ | ✅ |
| Open-source core | ❌ | ❌ | ❌ | ✅ |

## Appendix C — What's already built vs. what's planned

| Capability | Status |
|---|---|
| 4-agent pipeline (Ingest / Structure / Execute / Feedback) | ✅ shipped |
| AMD MI300X via vLLM, per-task model routing | ✅ shipped |
| Multimodal ingestion (PDF, DOC, DOCX, TXT, MD, CSV, PNG/JPG via VLM) | ✅ shipped |
| Directed knowledge graph with 10-verb relation set | ✅ shipped |
| Supersession + conflict detection + temporal status | ✅ shipped |
| 5-signal hybrid retrieval with RRF + temporal rerank | ✅ shipped |
| Verifier-triggered answer revision | ✅ shipped |
| `SKILLS.md` / `SKILLS.json` export, per-department | ✅ shipped |
| Knowledge gap analysis | ✅ shipped |
| Live AMD MI300X metrics panel | ✅ shipped |
| MCP server | 🟡 next |
| Live Slack / Notion / GitHub webhook ingest | 🟡 next |
| Active-learning loop (brain asks the company on Slack) | 🟡 next |
| First-class `/conflicts` resolution UI | 🟡 next |
| Temporal time-travel UI ("show the brain as of 2026-04-01") | 🟡 next |
