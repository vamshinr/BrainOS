# BrainOS — A Living Operating System for Company Knowledge

> **One-line:** The shared, structured memory that makes AI agents actually useful inside a company — by turning Slack, docs, diagrams, and tribal knowledge into a live graph that any agent can load before it acts.

---

## 1. The Problem

Every company runs on a corpus of knowledge that lives nowhere and everywhere:

- **60%** of operational knowledge is in Slack threads.
- **15%** is in Notion / Confluence pages that go stale within months.
- **10%** is in Google Docs no one reopens.
- **8%** is buried in Linear/Jira tickets and PR descriptions.
- **5%** is locked in Loom recordings and meeting transcripts.
- The rest — *the most valuable part* — is in three engineers' heads.

The cost of this fragmentation is enormous and quantifiable:

- **3–6 months** for a new hire to become productive — most of that is context absorption, not skill acquisition.
- **2.5 hours per week per engineer** spent searching for information they know exists somewhere (McKinsey Global Institute).
- When a senior engineer leaves, **40% of their tribal knowledge evaporates** within 30 days.
- AI coding agents (Claude Code, Cursor, Devin) hit a wall: they can write code beautifully, but they don't know your team's conventions, who owns what service, why you chose Stripe over Adyen, or that the webhook handler silently drops on a missing signature header.

**The new bottleneck isn't writing code. It's giving the AI enough context to write the *right* code.**

---

## 2. Why Existing Solutions Don't Solve This

| Tool | What it does | Why it falls short |
|---|---|---|
| Glean / Coveo | Federated enterprise search | Returns documents, not facts. No graph, no reconciliation, no agent integration. |
| Notion AI | Chat over your Notion | Single-source. Can't see Slack, can't see diagrams, doesn't extract structure. |
| Mem.ai / Reflect | Personal memory | Designed for one user, not a company. |
| Slack AI | Summarizes channels | Surface-level. Doesn't build durable knowledge. |
| Custom RAG | Ad-hoc per team | Just vector search over text. No relationships, no superseding, no provenance. |
| Devin / Cursor | Code-aware agents | Brilliant at code, blind to *the company that wrote it*. |

Every existing tool optimizes for *retrieval*. None of them produce a **structured, executable map of how the company actually works** that an AI agent can load before reasoning.

---

## 3. The Insight

Three things just became true at the same time, and BrainOS sits at their intersection:

1. **Open-weight LLMs (70B-class) and VLMs (7B-class) are good enough** to extract structured facts and relationships from messy real-world inputs — Slack, PDFs, whiteboard photos, architecture diagrams.
2. **AI agents are starting to consume "skills files"** — Anthropic's Claude Skills, OpenAI's GPTs, Cursor's `.cursorrules`, Aider's conventions. There is now a stable target format for *agent-shaped knowledge*.
3. **AMD MI300X (192 GB HBM3)** lets a single GPU host a 70B text model + a 7B VLM + a dedicated embedding model concurrently with no model-swap latency — making real-time multimodal ingestion economically viable.

The wedge: **AI agents need a graph, not a search index.**

---

## 4. What BrainOS Is

A multi-agent system that ingests every form of company knowledge — text, images, PDFs, recordings — and produces three artifacts:

1. **A live knowledge graph** (`brain.json`): entities (people, teams, systems, products), atomic knowledge units (facts, processes, policies, decisions, ownership, gotchas), and **directed relationships** (`Alice → owns → billing-svc`, `billing-svc → depends-on → Stripe`).
2. **A semantic index** (ChromaDB): embeds every fact for fuzzy retrieval.
3. **A `SKILLS.md` export**: an agent-loadable distillation that drops into Claude Code's `CLAUDE.md`, OpenAI's GPT instructions, or Cursor's rules. *This* is what makes BrainOS load-bearing infrastructure rather than a chatbot.

**Four agents, each doing one thing well:**

- **IngestionAgent** — reads raw input (text, image, PDF). VLM converts visual content to rich descriptions; text LLM extracts entities, atomic units, and directed relationships.
- **StructuringAgent** — embeds units into ChromaDB, runs reconciliation (`supersedes` / `duplicate` / `independent`) so the brain *resolves contradictions* instead of accumulating them, and merges into the graph.
- **ExecutionAgent** — answers questions via graph-aware hybrid retrieval: vector search → one-hop graph walk → grounded generation. Returns the exact source sentences fed to the model so users can trace any claim.
- **FeedbackAgent** — second-pass groundedness check. Returns confidence + grounded boolean; flags answers the model fabricated.

---

## 5. Why This Isn't Just RAG

Five capabilities that no production RAG system has and that compound into a moat:

1. **Directed knowledge graph.** Not co-mention. Real verbs (`owns`, `manages`, `depends-on`, `replaces`, `reports-to`, `governs`) extracted by the LLM and visualized as a navigable map. Enables structural queries impossible in vector space.
2. **Reconciliation as a primitive.** When you ingest "Alice owns billing" and later "Bob took over billing," BrainOS marks the old fact stale and supersedes it. RAG silently keeps both, then hallucinates.
3. **Multimodal extraction.** A diagram becomes graph edges. A whiteboard photo becomes process knowledge. A recorded standup becomes ownership facts. RAG sees only text.
4. **Agent-shaped output.** The brain compiles to a skills file consumable by every major AI agent platform. The brain isn't read by humans — it's loaded by Claude before it writes a PR.
5. **Provenance and confidence.** Every fact links back to its source quote with a confidence score. Agents can refuse low-confidence claims; humans can audit any answer.

**Coming next (months 1–3):**

- **Conflict detection.** Surface disputes ("Two sources disagree on `billing-svc` owner") instead of silently picking one.
- **Temporal facts.** Every unit has `validFrom` / `validTo`. "Who owned billing in Q1 vs Q3?" becomes a real query.
- **Active-learning loop.** When confidence is low, the brain *asks the company* on Slack and learns from the answer.
- **Live ingest streams.** Webhook listeners on Slack / Notion / GitHub → continuous extraction. The brain that watches the company while you sleep.
- **Knowledge gap detection.** Periodic scan of orphan nodes ("`payments-svc` has no documented owner"), surfaced as a punch list.

---

## 6. Why Now

- **2023:** GPT-4 made retrieval-augmented generation interesting, but the LLMs were too expensive to run extraction at scale.
- **2024:** Open-weight LLMs (Llama 3, Mistral, Qwen) hit "good enough" quality for fact extraction at 1/100th the cost.
- **2025:** Open-weight VLMs (Qwen2.5-VL, LLaVA) cross the threshold for production diagram and screenshot understanding.
- **2025:** AMD MI300X reaches general availability — 192 GB HBM3 makes co-resident text + vision + embedding models economical.
- **2025:** Anthropic Skills, OpenAI Custom GPTs, Cursor rules — every major agent now consumes a "context file." The plug exists; nothing fills it for company-wide knowledge.

This window did not exist 18 months ago. It will close in 18 more.

---

## 7. The Demo (60 seconds)

1. Drop a Slack export, a runbook PDF, and a whiteboard photo into the ingest box.
2. Watch the **knowledge graph populate live** — nodes for Alice, Bob, billing-svc, Stripe; edges for `owns`, `depends-on`.
3. Ingest a *new* Slack message: "Bob is now on call for billing." The graph updates; the old "Alice owns billing" fact is marked superseded — visible as a strikethrough.
4. Ask "Who owns the billing service and what does it depend on?" → grounded answer with source citations and a confidence score.
5. Click **Export → SKILLS.md** → drop it into a Claude Code session → ask Claude to "open a PR to update Stripe API key rotation" → it knows who to tag, what runbook to follow, and which gotchas to avoid.

Five minutes from cold codebase to an AI agent that knows your company.

---

## 8. Architecture (technical credibility)

- **Frontend:** Next.js 15 App Router. Server Components read `brain.json` with mtime-aware caching so external writes are reflected without restart.
- **Backend:** FastAPI multi-agent orchestrator. Four specialized agents.
- **Inference:** vLLM serving 70B text + 7B VLM + embedding model concurrently on a single AMD MI300X.
- **Retrieval:** Hybrid (dense + sparse + entity-match) with reciprocal rank fusion, then one-hop graph walk for context expansion.
- **Storage:** ChromaDB (HNSW cosine) for vectors; `brain.json` (Git-friendly) for the graph.
- **Outputs:** REST API, Markdown skills file, JSON skills file, MCP server (planned).

Every layer is open-source, swappable, and self-hostable. No vendor lock-in is part of the pitch — companies can run the brain on their own infra.

---

## 9. Go-to-Market

**Beachhead:** Series-B engineering organizations (50–200 engineers) using Anthropic Claude / Cursor / GitHub Copilot. They feel the pain acutely (onboarding, turnover, agent context) and have budget.

**Wedge:** Free open-source self-hosted version. Paid hosted version with managed connectors (Slack, Notion, GitHub, Linear), SSO, audit logs.

**Expansion:** Once the brain is the source of truth for one team's AI agents, it becomes the natural source for *every* team. Sales becomes seat-based and viral within the org.

**Pricing (early):** $20 / engineer / month. A 100-engineer team = $24k ARR. 10 such teams = $240k ARR. Achievable in year one.

---

## 10. Moat

- **Workflow lock-in.** Once the brain feeds an org's AI agents, replacing it means re-extracting and re-validating thousands of facts. Switching cost is steep.
- **Data network effect.** Every correction, supersession, and feedback signal makes the extraction pipeline better — for *that customer*, on *their* idiosyncratic vocabulary.
- **Distribution via agent platforms.** Native integrations with Claude Skills, ChatGPT, Cursor — the brain is the upstream context provider for every agent the company uses.
- **Open-source community.** The skills-file format becomes a standard the way `package.json` or `Dockerfile` did.

---

## 11. Why This Team

[Founders write this section. Highlight: shipped multi-agent systems before, deep familiarity with the AI agent ecosystem, ground-truth pain from a previous engineering role, AMD partnership / GPU access for credibility.]

---

## 12. The Ask

Looking for **$1.5M seed** to:

- Hire 2 ML engineers (graph retrieval + extraction quality).
- Hire 1 full-stack engineer (connectors: Slack, Notion, GitHub, Linear).
- Get 5 design-partner companies on the hosted version.
- Reach $100k ARR within 12 months.

**Status:** Working multi-modal prototype. Live multi-agent system on AMD MI300X. Demo-ready knowledge graph with directed relationships, supersession, provenance, and skills-file export. Ready to onboard the first three design partners next month.

---

## Appendix A — One-paragraph version (for cold emails / Twitter)

> BrainOS turns scattered company knowledge — Slack, docs, diagrams, recordings — into a structured graph that AI agents load before they act. Built on AMD MI300X, four specialized agents extract entities, directed relationships, and atomic facts; reconcile contradictions; and compile a `SKILLS.md` consumable by Claude, ChatGPT, and Cursor. Not a search tool. The first operating system for company knowledge in the agent era.

## Appendix B — Comparison table (use in deck)

| | RAG chatbot | Glean | Notion AI | **BrainOS** |
|---|---|---|---|---|
| Returns documents | ✅ | ✅ | ✅ | ✅ |
| Returns atomic facts | ❌ | ❌ | ❌ | ✅ |
| Directed relationship graph | ❌ | ❌ | ❌ | ✅ |
| Reconciles contradictions | ❌ | ❌ | ❌ | ✅ |
| Multimodal (diagrams, screenshots) | ❌ | partial | ❌ | ✅ |
| Provenance + confidence per fact | ❌ | ❌ | ❌ | ✅ |
| Compiles to agent skills file | ❌ | ❌ | ❌ | ✅ |
| Self-hostable | ❌ | ❌ | ❌ | ✅ |
| Open-source core | ❌ | ❌ | ❌ | ✅ |
