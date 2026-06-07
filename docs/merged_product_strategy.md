# Merged Product Strategy: BrainOS × SemanticOS on Graphiti

**Document owner:** Vamshi + co-founder (BrainOS)
**Counterparty:** Julian (SemanticOS / semanticos.io)
**Last updated:** 2026-05-24
**Status:** Pre-collaboration strategy doc — for internal alignment and as a shareable artifact to Julian

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architectural Thesis](#2-architectural-thesis)
3. [The Graphiti Baseline (what's free)](#3-the-graphiti-baseline)
4. [Pricing Strategy](#4-pricing-strategy)
5. [Improvement Catalog (18 features in 5 layers)](#5-improvement-catalog)
   - [A. Intelligence Layer (5 features)](#a-intelligence-layer)
   - [B. Quality Layer (4 features)](#b-quality-layer)
   - [C. Agent Layer (4 features)](#c-agent-layer)
   - [D. Enterprise Layer (3 features)](#d-enterprise-layer)
   - [E. Insights Layer (3 features)](#e-insights-layer)
6. [ARR Impact Model](#6-arr-impact-model)
7. [Build Prioritization (12-month roadmap)](#7-build-prioritization-12-month-roadmap)
8. [Quarter 1 Engineering Plan (detailed)](#8-quarter-1-engineering-plan)
9. [Key Risks & Mitigations](#9-key-risks--mitigations)
10. [Open Questions for Julian](#10-open-questions-for-julian)
11. [Next Steps](#11-next-steps)

---

## 1. Executive Summary

### The Thesis

**Build BrainOS as the cognitive layer on top of Graphiti's temporal-graph substrate, integrated with SemanticOS's ingestion pipeline.** This unifies three stacks:

- **SemanticOS** brings the data in (Airbyte 350+ connectors → Kafka streaming).
- **Graphiti** is the substrate (bi-temporal knowledge graph on Neo4j/FalkorDB).
- **BrainOS** is the intelligence (typed knowledge units, reconciliation verdicts, multi-modal extraction, FeedbackAgent groundedness audit, SKILLS export, MCP tool surface).

### The Outcome

Same 100 customers, **5.2× ARR multiplier**: from $12M (Graphiti + Airbyte baseline) to $62M (full merged stack). At 500 customers (Julian's Year 3 target), this **exceeds the $100M ARR milestone by 25–55%**.

### The Sequencing

Six weeks of porting work (Q1) takes a single customer from $24K → $240K ARR — using code BrainOS has already built. Quarters 2–4 add enterprise unlocks and a premium SKU that brings the average customer to **$1M ARR over 24 months**.

### The Honest Caveats

- Brand collision (SemanticOS vs BrainOS) is a real conversation neither side has had yet.
- SemanticOS's Sep 2025 doc is 8 months old; Julian flagged Skills + "other things now play in our favor" — we need a current architecture view before committing.
- "Production-ready" claim from SemanticOS deserves polite verification.
- Both stacks would inherit a coupling to Graphiti's roadmap.

---

## 2. Architectural Thesis

```
┌──────────────────────────────────────────────────────────────┐
│  AGENT SURFACE                                               │
│  Claude Code · Cursor · Devin · custom agents                │
└────────────────────────────┬─────────────────────────────────┘
                             │ MCP tools, REST, Slack, Webhooks
┌────────────────────────────┴─────────────────────────────────┐
│  E. INSIGHTS LAYER (new premium SKU)                         │
│  Belief Layer · Outcome-Linked Memory · Federated Priors     │
└────────────────────────────┬─────────────────────────────────┘
┌────────────────────────────┴─────────────────────────────────┐
│  B. QUALITY LAYER (defensibility)                            │
│  FeedbackAgent · Decay Scheduler · Active Learning Loop      │
└────────────────────────────┬─────────────────────────────────┘
┌────────────────────────────┴─────────────────────────────────┐
│  D. ENTERPRISE LAYER (Enterprise-tier unlocks)               │
│  Audit Log · ACL · GDPR Deletion · Time-Snapshots            │
└────────────────────────────┬─────────────────────────────────┘
┌────────────────────────────┴─────────────────────────────────┐
│  A. INTELLIGENCE LAYER (the BrainOS core differentiator)     │
│  Typed Units · Reconciliation Verdicts · VLM · SKILLS export │
└────────────────────────────┬─────────────────────────────────┘
┌────────────────────────────┴─────────────────────────────────┐
│  GRAPHITI SUBSTRATE (free from OSS)                          │
│  Bi-temporal edges · Hybrid retrieval · Neo4j scale          │
└────────────────────────────┬─────────────────────────────────┘
┌────────────────────────────┴─────────────────────────────────┐
│  INGESTION (SemanticOS already built this)                   │
│  Airbyte 350+ connectors · Kafka streaming                   │
└──────────────────────────────────────────────────────────────┘
```

### Layer ownership map

| Layer | Built by | Status |
|---|---|---|
| Ingestion | SemanticOS | Built |
| Substrate | Graphiti OSS | Built (consume directly) |
| Intelligence | BrainOS | Built (port to Graphiti backend) |
| Enterprise | BrainOS (new) | To build (Q3) |
| Quality | BrainOS (partial) | FeedbackAgent built; rest Q4 |
| Insights | BrainOS (new) | To build (Q4 + Year 2) |
| Agent Surface | BrainOS (partial) | MCP tools built; rest Q2 |

---

## 3. The Graphiti Baseline

Before adding anything, inheriting from Graphiti gives:

| Capability | Value |
|---|---|
| Bi-temporal edges (`occurred_at` + `ingested_at`) | Time-travel queries work natively |
| Soft-invalidation via `valid_to` | History never lost |
| Hybrid retrieval (semantic + BM25 + graph traversal) | Day-one retrieval quality |
| Neo4j / FalkorDB / Kuzu / Neptune backend | Scale to billions of edges |
| Pydantic ontology | Typed entity/edge schemas |
| Episodes as provenance unit | Every fact traces to its source |
| Real-time incremental updates | No batch recomputes |

**Baseline ARR per customer with just Graphiti + Airbyte:** $120K (Professional tier). This is roughly where SemanticOS sits today.

**The strategic question:** what improvements take a customer from $120K → $600K → $1M+ ARR?

---

## 4. Pricing Strategy

Julian's existing tier structure, kept, with two new tiers added:

| Tier | Price/mo | ARR | Target |
|---|---|---|---|
| Starter | $2K | $24K | SMB, ≤10 sources |
| Professional | $10K | $120K | Mid-market, unlimited sources |
| Enterprise | $50K+ | $600K+ | F500, compliance, ACL, audit |
| **+ Insights add-on (new)** | **$15K** | **$180K** | Belief Layer + Outcome-Linked |
| **+ Federated tier (new)** | **$4K** | **$50K** | Cross-org pattern priors |

Each improvement in §5 is tagged with which tier it unlocks or expands.

---

## 5. Improvement Catalog

18 features across 5 layers. For each: what Graphiti has today, the improvement, a concrete demo, ARR impact, and build cost.

---

## A. INTELLIGENCE LAYER

### A1. Typed Unit Kinds

**Graphiti today:** Stores entities and edges. An edge has a `fact` string like "owns billing" but no *type of knowledge*.

**The improvement:** Every extracted unit gets a `kind` enum: `fact` / `process` / `decision` / `ownership` / `definition` / `policy` / `gotcha`. Tagged at extraction time by BrainOS's IngestionAgent.

**Demo:**
```
Input: "We chose Stripe over Adyen in Q2 2024 because of better SCA support.
        Alice owns billing infrastructure. Never deploy on Fridays — payout
        job runs Sunday 00:00 UTC."

Graphiti output (today):
  Entity(Stripe), Entity(Adyen), Entity(Alice), Entity(billing)
  Edge: Company --uses--> Stripe (valid_at 2024-04)
  Edge: Alice --owns--> billing
  Edge: deploys --blocked_on--> Friday

<MERGED> output:
  Unit u1: kind=decision,  "Chose Stripe over Adyen — SCA support",  confidence=0.92
  Unit u2: kind=ownership, "Alice owns billing infrastructure",       confidence=0.95
  Unit u3: kind=gotcha,    "No Friday deploys — payout Sunday 00 UTC", confidence=0.97
```

**Product UX this unlocks:**
- Department dashboards — "show me all `kind=ownership` units in engineering"
- Onboarding briefs — "show me all `kind=policy` units for new hires"
- Risk register — "show me all `kind=gotcha` units sorted by criticality"
- Decision archaeology — "why did we choose X over Y?" returns only `kind=decision`

**Tier unlock:** Professional ($120K).
**ARR impact:** **+$60K per customer.** Moves customers from "I have a graph DB" to "I have a navigable knowledge product."
**Build cost:** Already built in BrainOS. ~3 days to port `IngestionAgent` to write into Graphiti edges with `kind` as edge property.

---

### A2. Explicit Reconciliation Verdicts

**Graphiti today:** When the same statement arrives twice with different timestamps, Graphiti soft-invalidates the older one. No reason given.

**The improvement:** BrainOS's `StructuringAgent` calls an LLM verdict gate that classifies new vs existing units as `supersedes` / `duplicate` / `conflicts` / `independent`, with a `disputedReason` string when conflict is detected.

**Demo (supersession):**
```
Existing unit u_3201: "Bob Lee owns billing" (from 2024 doc, no end date)
New input:           "Alice now owns billing infra (effective March 1)"

Graphiti behavior:
  - Adds Alice → owns → billing edge with valid_at = 2026-03-01
  - Implicitly invalidates Bob's edge at the same date
  - No record of WHY

<MERGED> behavior:
  - StructuringAgent verdict: "supersedes"
  - u_3201: stale=true, supersededBy=u_4421, validTo=2026-03-01
  - u_4421: validFrom=2026-03-01, kind=ownership
  - Audit log: "Reconciliation: u_4421 supersedes u_3201, reason:
               'effective date specified in source, prior fact had no end date'"
```

**Demo (genuine conflict):**
```
Input A: "We're using Stripe for SMB checkout"
Input B: "We migrated everything to Adyen last month"

Graphiti: stores both, no signal
<MERGED>: both flagged disputed=true, conflictsWith=[other_id]
          Agent answer: "[DISPUTED] Two contradictory facts exist..."
          Compliance report: "23 disputed facts pending resolution"
```

**Tier unlock:** Enterprise ($600K). Compliance and risk teams require explicit "show me what the system is uncertain about" reports — needed for SOC2 Type II, ISO 27001, financial-services audits.
**ARR impact:** **+$200K per customer** in regulated verticals. Without verdicts you can't sell to them at all.
**Build cost:** Already built. Port `StructuringAgent._reconcile()` to operate against Graphiti queries instead of `brain.json`. ~1 week.

---

### A3. Multi-modal VLM Pipeline

**Graphiti today:** Text only. An architecture diagram is opaque to it.

**The improvement:** BrainOS's `IngestionAgent._extract_image()` routes PNGs/PDFs through a VLM (Qwen2.5-VL or LLaVA), produces structured prose, then runs the same typed-unit extraction.

**Demo:**
```
Input: 1 photo of a whiteboard from a design session
       (handwritten boxes, arrows, annotations)

Graphiti: cannot ingest. Image stored as opaque blob if at all.

<MERGED> output (in 30 seconds):
  Entity: "checkout-service"
  Entity: "payments-service"
  Entity: "fraud-detection"
  Edge: checkout --calls--> payments  (via gRPC)
  Edge: payments --depends_on--> fraud-detection
  Edge: payments --integrates_with--> Stripe API
  Unit (kind=gotcha, conf=0.88):  "Never bypass fraud check between
                                   checkout and payments"
  Unit (kind=decision, conf=0.82): "Chose gRPC over REST for internal
                                    service mesh"
```

**Why this is huge:**
- 30%+ of architectural knowledge lives in diagrams (Lucid, Miro, whiteboard photos, Confluence embeds).
- Every other memory system in market (Mem0, Letta, Cognee, Zep, Graphiti raw) is text-only.
- VLM ingestion is the only way to capture this knowledge programmatically.

**Tier unlock:** Add-on at **+$30K/year** to any tier, or bundled into Professional+.
**ARR impact:** **+$30K per customer** as add-on; OR justifies 20% Professional uplift to $144K.
**Build cost:** Already built. Plug into Graphiti substrate the same way text extraction does.

---

### A4. Department-Specific Extraction Prompts

**Graphiti today:** One generic extraction prompt for all data.

**The improvement:** Extraction prompt is selected per source's department (engineering vs legal vs finance vs HR). Engineering extracts `gotcha` and `decision` types aggressively; legal extracts `policy` types; finance extracts `ownership` and `process` types.

**Demo:**
```
Same Slack message: "FYI we're moving Stripe rate limit to 200rps for SMB
                     accounts effective next Monday"

Generic extraction (Graphiti):
  Entity(Stripe), Entity(SMB accounts)
  Edge: Stripe --rate_limit--> 200rps

Engineering-tuned extraction (<MERGED>):
  Unit (kind=decision, dept=engineering, conf=0.94):
    "Stripe rate limit increasing to 200rps for SMB accounts on [date]"
  Unit (kind=gotcha, dept=engineering, conf=0.85):
    "Rate limit change Monday may affect downstream services not retried"
  Auto-link: previous unit u_4421 (Alice owns billing) → notification

Finance-tuned extraction (<MERGED>):
  Unit (kind=fact, dept=finance, conf=0.90):
    "Stripe usage tier increasing — review SaaS spend implications"
  Auto-link: previous unit u_2330 (SaaS budget Q2)
```

**Tier unlock:** Enables per-department expansion sales — each new department added is a separate product instance.
**ARR impact:** **+$120K per customer over 18 months** via expansion (avg 4 new departments at $30K each).
**Build cost:** ~2 weeks to refactor `EXTRACTION_SYSTEM` prompt into department-templated variants.

---

### A5. Confidence Scoring & Evidence Quotes

**Graphiti today:** All edges treated equally. No confidence; no evidence quote.

**The improvement:** Every unit has `confidence` (0.0–1.0) and `evidence` array with literal source quotes + source IDs.

**Demo (high confidence):**
```
Query: "Who owns billing?"

Graphiti answer:
  "Alice Chen owns billing." (from edge)

<MERGED> answer:
  "Alice Chen owns billing infrastructure [F1].
   Confidence: 0.95
   Evidence quote: 'Alice now owns billing infra (effective March 1)'
   Source: #billing-team Slack, 2026-04-12 14:23 UTC"
```

**Demo (low confidence):**
```
Query: "Who owns the new fraud system?"

<MERGED> answer:
  "There is no direct ownership statement on file for the fraud system.
   Inferred (confidence 0.42): Priya Shah may be the owner based on
   a Linear ticket she filed [F1].
   Evidence quote: 'I'll take the fraud sub-task'
   Recommendation: confirm with @priya or the SRE channel."
```

**Tier unlock:** Foundational for everything else (audit, FeedbackAgent, etc.).
**ARR impact:** No direct tier driver, but **prevents 30% churn** that would otherwise come from "the AI made stuff up." Worth ~$40K/customer in retention.
**Build cost:** Already built. Becomes edge properties in Graphiti.

---

## B. QUALITY LAYER

### B1. FeedbackAgent / Groundedness Audit

**Graphiti today:** No answer layer. You get edges; your agent generates the answer. If it hallucinates, you don't know.

**The improvement:** Every answer from `ExecutionAgent` is audited by `FeedbackAgent` — a second LLM call that verifies every claim in the answer is grounded in the retrieved context. If `grounded=false` OR `confidence < 0.72`, automatic revision.

**Demo:**
```
Query: "Who approved the Q4 budget increase?"

Draft answer (ExecutionAgent):
  "Sarah from Finance approved the Q4 budget increase on March 15."

FeedbackAgent audit:
  {
    "grounded": false,
    "unsupported_claims": [
      "Sarah from Finance approved" — no unit cites approval,
      "on March 15" — date not in any retrieved context
    ],
    "confidence": 0.31
  }

Revised answer (auto-triggered):
  "The system has no record of formal approval for the Q4 budget increase.
   Relevant facts found: Sarah from Finance discussed the budget on
   2026-03-12 [F1] but no explicit approval is documented.
   Recommendation: confirm with @sarah or check the approvals channel."

UI badge: [Grounded · 0.91 confidence · revised once]
```

**Why this is a $250K/customer feature:** Enterprise buyers will ask "but does it hallucinate?" 100% of the time. Without FeedbackAgent the demo dies on that objection. With it you have a verifiable answer. This is *the* kill-shot against Glean and Moveworks who lose deals on hallucination concerns.

**Tier unlock:** Required for Professional+ ($120K). Enables Enterprise ($600K).
**ARR impact:** **+$250K per customer** — this is the single feature that closes Enterprise deals.
**Build cost:** Already built. ~1 week to port to Graphiti retrieval.

---

### B2. Knowledge Decay Scheduler

**Graphiti today:** Edges live forever unless explicitly invalidated by new contradicting input.

**The improvement:** Per-`kind` half-life. Gotchas decay in 365d, ownership in 90d, decisions never. When a unit hits its half-life, confidence drops 50% and it's flagged for re-verification.

**Demo:**
```
2026-01-15: Unit u_7102 created: "Never deploy billing on Fridays"
            kind=gotcha, confidence=0.97, half_life=365d

2027-01-15 (1 year later): Decay scheduler triggers
  → u_7102.confidence drops to 0.49
  → u_7102.flagged_for_review = true

Active learning loop fires (see B3):
  → DM to @platform-eng channel: "Quick check — is the 'no Friday
    deploys' gotcha still valid? Last confirmed 2026-01-15."

Response: "Yes, still valid — payout job runs every Sunday."
  → u_7102.confidence restored to 0.95
  → u_7102.last_verified = 2027-01-15

Alternative response: "No, we moved payout to Wednesday in October."
  → u_7102 supersededBy new unit
  → u_7102.stale = true
```

**Tier unlock:** Quality/retention feature — keeps the brain from rotting silently.
**ARR impact:** **+$50K per customer in retention.** Without this, year-2 churn spikes because customers complain the brain is "confidently wrong."
**Build cost:** 3 days. Scheduled job hitting Graphiti edges, decrementing confidence.

---

### B3. Active Learning Loop (Inquisitor)

**Graphiti today:** Passive. Knows nothing about gaps in its own knowledge.

**The improvement:** When a query returns low-confidence answer OR a unit's half-life triggers OR conflicts surface, the system DMs the responsible human on Slack to confirm.

**Demo:**
```
Query (from CFO): "What's our current payment processor?"

ExecutionAgent finds conflicting units u_5511 (Stripe) and u_5512 (Adyen).
FeedbackAgent flags: confidence=0.4, contradictions present.

Inquisitor triggers:
  Slack DM to @platform-eng-lead:
    "Quick clarification needed — the brain has conflicting facts:
     1. 'Using Stripe for SMB' (#payments-team, Apr 12)
     2. 'Migrated everything to Adyen' (#sales, Apr 18)
     Which is correct? React with 1️⃣ or 2️⃣, or reply with the full picture."

Response: "1 for SMB, Adyen is enterprise only. We use both."

Brain updates:
  u_5511: refined to "Stripe used for SMB checkout"
  u_5512: refined to "Adyen used for enterprise checkout"
  conflictsWith cleared on both
  NEW unit: "Company uses both Stripe (SMB) and Adyen (Enterprise)"
```

**Tier unlock:** Premium feature — part of Insights SKU ($180K).
**ARR impact:** **+$60K per customer expansion** + **+$80K retention** (extremely sticky once teams rely on the active feedback loop).
**Build cost:** ~3 weeks. Slack integration + Inquisitor agent + verdict ingestion.

---

### B4. Outcome-Linked Memory

**Graphiti today:** Static. Retrieval quality fixed.

**The improvement:** Every Q&A emits a feedback signal back to retrieved units. Units cited in `FeedbackAgent.grounded=true` answers get usefulness boost; units never cited or cited in failed answers decay. RRF retrieval weights *learn* per question class.

**Demo (6-month trajectory):**
```
Day 1, retrieval quality test: 67% of answers grounded
  - Vector signal weighted 0.3, BM25 0.3, entity 0.2, graph 0.2
  - Same weights for "who owns X" as "why did we choose X"

Day 30, system has logged 4,000 Q&A pairs with feedback scores:
  - Discovered: "who owns X" type queries → entity-index signal predicts
    grounded answer in 89% of cases vs vector at 71%
  - Discovered: "why did we choose X" → graph-walk signal predicts
    grounded answer at 82% vs entity at 54%
  - RRF re-weights per question class

Day 180, retrieval quality: 84% grounded (vs 67% baseline)
  - 17pp improvement, zero engineering work
  - Compounds with usage

Concrete user-visible effect:
  Day 1:   "Who owns billing?" → may return Alice OR Bob (50/50, conf 0.6)
  Day 180: "Who owns billing?" → returns Alice first, conf 0.93
           (because u_4421 has usefulness=0.94 from 142 successful citations,
            u_3201 has usefulness=0.12 from 2 failed citations)
```

**Why this is a strategic moat:** Every Mem0/Zep/Letta/Cognee instance is static. Yours gets *better the more it's used*. Day-1 you're at parity; day-180 you've left them behind.

**Tier unlock:** Bundled into Insights SKU ($180K) OR part of Professional+ as quality differentiator.
**ARR impact:** **+$80K per customer** (justifies premium pricing) + **+$120K in retention** (lock-in compounds with usage).
**Build cost:** ~2 weeks. Wire `FeedbackAgent.confidence` back to edge properties; tune RRF weights via online learning.

---

## C. AGENT LAYER

### C1. MCP Tool Surface

**Graphiti today:** Python library. Exposes Cypher and search functions. Any agent integration is custom code.

**The improvement:** Pre-built MCP server exposing 10 high-level tools: `ask_brain`, `search_facts`, `lookup_entity`, `get_relationships`, `get_graph_summary`, `detect_failures`, `ingest_text`, `export_skills`, `analyze_gaps`, `get_metrics`.

**Demo:**
```
Without MCP tools (Graphiti raw):
  Cursor developer wants to integrate. Writes:
    - Custom retrieval pipeline (200 lines)
    - Custom answer-synthesis prompt (150 lines)
    - Custom citation handling (80 lines)
  Total: 2 days of integration work.

With <MERGED> MCP tools:
  Add to mcp.json:
    {
      "<merged>": {
        "command": "merged-mcp",
        "args": ["--brain-url", "https://acme.merged.io"]
      }
    }
  Done. Cursor now has 10 tools available. Total: 5 minutes.

Demo query in Cursor:
  Dev: "Who should I ask about the billing rate-limit change?"
  Cursor calls: lookup_entity{"name":"billing"}
                → returns owner Alice, recent changes, gotchas
  Cursor calls: get_relationships{"entity":"Stripe","depth":1}
                → returns rate-limit history
  Cursor synthesizes: "Alice Chen (@alice) owns billing. The Stripe
    rate limit was increased to 200rps on 2026-03-01. Before changing
    it, note that #payments-team has a no-Friday-deploys rule."
```

**Tier unlock:** Drives **seat expansion** dramatically. Every dev with Cursor/Claude Code becomes a daily user.
**ARR impact:** **+$80K per customer** through seat expansion (avg 30 more dev seats unlocked) + **-40% CAC reduction** (5-minute integration > 2-day integration).
**Build cost:** ~1 week. Already partially built in `brainos_agent/tools.py`.

---

### C2. SKILLS.md Export Per Department

**Graphiti today:** No equivalent. Agents query the graph live, paying retrieval cost on every query.

**The improvement:** Department-scoped distillation as agent-loadable markdown. Loaded once at session start; cached as prefix.

**Demo (cost math):**
```
Without SKILLS.md (raw Graphiti):
  Every Cursor session, every query:
    - 3 retrieval calls (~500ms latency, $0.003 cost)
    - 1 answer-gen call ($0.005)
  100 devs × 50 queries/day × $0.008 = $40/day = $14K/year

With SKILLS.md preloaded:
  Session start: load engineering/SKILLS.md once
    - 1 call ($0.001 cached prefix)
    - 8KB of distilled knowledge in context
  Subsequent queries: zero retrieval calls for 80% of queries
                      (the common stuff is already in context)
  100 devs × 50 queries/day × $0.0015 = $7.5/day = $2.7K/year

  Savings: $11.3K/year per customer in inference costs alone.
  Plus latency drops from 800ms → 50ms per query.
```

**Demo (sample output):**
```markdown
# Engineering SKILLS — auto-generated 2026-05-24

## Ownership (12 systems)
- billing → Alice Chen (@alice), since 2026-03-01
- checkout → Bob Lee → moved to search team
- fraud-detection → Priya Shah (@priya), since 2025-08-15
[...]

## Policies (4)
- All prod deploys require two reviewers
- Never deploy billing on Fridays (payout Sunday 00:00 UTC)
- All new services emit OpenTelemetry
- Secrets rotated quarterly via Vault

## Gotchas (7)
- Stripe webhook timeout is 30s, retries at-least-once
- users table has soft-delete — filter deleted_at IS NULL
[...]

## Decisions (recent, 3)
- 2024-Q2: Stripe over Adyen for SMB (SCA support)
- 2026-Q1: vLLM over TGI (MI300X native)
[...]

## Active Conflicts [DISPUTED]
- u_5511 vs u_5512: Stripe vs Adyen — split by SMB/Enterprise (resolved)
```

**Tier unlock:** Drives **seat expansion** and **per-department upsell.** Each new department = new SKILLS.md = new product instance.
**ARR impact:** **+$100K per customer** via 4-department expansion at $25K/dept.
**Build cost:** Already built in BrainOS. ~3 days to port to Graphiti backend.

---

### C3. Slack-Native Query Interface

**Graphiti today:** Has to be queried via API. No native chat interface.

**The improvement:** First-class Slackbot. `@brain who owns billing?` in any channel returns inline-cited answer.

**Demo:**
```
In #engineering:
  Sarah: "@brain who owns billing service?"

  Brain (1.2s later, inline):
    Alice Chen (@alice) has owned billing since 2026-03-01 [F1].
    Before any changes, see gotcha: no Friday deploys (payout Sunday) [F2].

    [Sources] [Edit] [Mark stale]

  Tom: "@brain why did we choose Stripe?"

  Brain:
    Decided 2024-Q2 by Alice, Priya, Marcus [F1]. Reason: Stripe's SCA
    support was stronger than Adyen's at the time for SMB markets [F2].
    Note: this decision is 2 years old; if context has changed, mark stale.

    [Sources] [Edit] [Mark stale]
```

**Why this drives ARR:** Slack is where knowledge work happens. The brain has to be *where employees are*, not behind a separate URL.

**Tier unlock:** Foundational for Professional+ ($120K).
**ARR impact:** **+$60K per customer** + **dramatic adoption uplift** (5x more queries per employee per week vs. separate web UI).
**Build cost:** ~2 weeks. Slack bot + thread context handling + edit/mark-stale loop.

---

### C4. Webhook Subscriptions / Event Triggers

**Graphiti today:** Read-only graph queries.

**The improvement:** Subscribe to events: "notify when ownership changes," "alert when a new conflict appears," "ping when a policy gets added."

**Demo (three use cases):**
```
Use case 1: Incident Commander Bot
  Subscribes: kind=ownership changes for systems billing|checkout|payments
  Trigger: u_3201 superseded by u_4421
  Action: Post in #incidents-runbook channel:
    "🔔 billing service ownership changed: Alice Chen → (was: Bob Lee)
     Updating runbook escalation paths..."

Use case 2: Compliance Reviewer
  Subscribes: kind=policy added or modified
  Trigger: New policy unit "All AI features require legal review"
  Action: Email legal team + create Jira ticket to update playbook

Use case 3: Onboarding Bot
  Subscribes: any unit added with department=hr OR kind=policy
  Trigger: every Monday at 9am, summarize prior week's policy changes
  Action: Email all-hands with "What's new this week in company knowledge"
```

**Tier unlock:** Enterprise ($600K) — integration into existing workflows.
**ARR impact:** **+$50K per customer** + **+$40K retention** (workflow integration = sticky).
**Build cost:** ~2 weeks. Event bus + subscription store + delivery worker.

---

## D. ENTERPRISE LAYER

### D1. Audit Log & Compliance Reports

**Graphiti today:** Edge history exists but no structured audit log; no compliance reports.

**The improvement:** Every read, write, reconciliation, deletion is logged with `actor`, `timestamp`, `unit_id`, `action`, `justification`. Pre-built compliance reports: SOC2, GDPR, HIPAA, ISO 27001.

**Demo (GDPR deletion):**
```
GDPR data deletion request: User X requests deletion of all their data

Without audit log:
  Engineer manually queries Slack, Notion, GitHub for User X
  Estimated effort: 40 hours. Risk of missing 10%+ of data. Non-compliant.

With <MERGED> audit log:
  POST /api/compliance/gdpr/delete?user=user_x_id

  System runs:
    1. Find all units where entities contains User X (12 units)
    2. Find all units derived from sources owned by User X (47 units)
    3. Find all units where evidence_quote mentions User X (8 units)
    4. Generate deletion plan with justifications
    5. Execute deletion (soft-invalidate or hard-delete per policy)
    6. Emit audit trail: "GDPR delete for user_x: 67 units affected,
                          14 edges invalidated, 4 entities anonymized"

  Output: Full compliance report PDF, deletion certificate, audit trail.
  Time: 8 minutes. Compliant. Defensible in deposition.
```

**Demo (SOC2 report):**
```
SOC2 Type II Quarterly Report (auto-generated):
  "In Q1 2026, the system processed 487,000 knowledge events.
   - 47 facts flagged as disputed (resolution rate 91%)
   - 12 high-confidence reconciliations (supersedes verdict)
   - 0 unauthorized accesses
   - 100% of edges have evidence provenance
   - Mean confidence: 0.84"
```

**Tier unlock:** Enterprise ($600K). Required for any sale to financial services, healthcare, government.
**ARR impact:** **+$400K per Enterprise customer.** Without this you cannot sell to F500.
**Build cost:** ~4 weeks. Audit log infrastructure + report templates + GDPR workflow.

---

### D2. ACL by Department / User

**Graphiti today:** No native ACL.

**The improvement:** Every unit has `department` and `read_acl[]` properties. Queries automatically filter to caller's permissions.

**Demo:**
```
Brain contains:
  u_1: "Alice salary is $245K"          (department=hr, acl=[hr,exec])
  u_2: "Alice owns billing"             (department=engineering, acl=[*])
  u_3: "Vault token rotation: monthly"  (department=security, acl=[security,sre])

Sales rep queries: "what does Alice work on?"
  Filtered context: only u_2 visible (acl=[*])
  Answer: "Alice owns billing infrastructure."

HR queries: "what does Alice work on?"
  Filtered context: u_1 + u_2
  Answer: "Alice owns billing; her compensation is in HR records."

SRE queries: "what does Alice work on?"
  Filtered context: u_2 + u_3 (visible to security/sre)
  Answer: "Alice owns billing. Note: monthly Vault token rotation policy."
```

**Tier unlock:** Enterprise ($600K). Multi-department deployment is impossible without this.
**ARR impact:** **+$300K per Enterprise customer** + **enables 10x more departments to be added** (= expansion revenue).
**Build cost:** ~3 weeks. ACL property on edges + query-time filter + admin UI for ACL management.

---

### D3. Time-Windowed Snapshots / Brain Diff

**Graphiti today:** Bi-temporal queries exist but no first-class "snapshot at date X" or "diff between two snapshots."

**The improvement:** `GET /api/snapshot?date=2026-01-01` returns the full brain state as of that date. `GET /api/diff?from=2026-01-01&to=2026-05-01` returns changes between two states.

**Demo (board prep):**
```
CEO: "How has our knowledge graph evolved this quarter?"

GET /api/diff?from=2026-01-01&to=2026-04-01

Returns:
  Summary:
    - 1,247 new units added
    - 89 facts superseded (mostly ownership changes from reorg)
    - 14 conflicts resolved
    - 3 new departments onboarded (legal, sales-ops, design)
    - Knowledge coverage: 67% → 79%

  Top 10 changes by impact:
    1. Ownership reorg: 23 system owners changed
    2. New compliance policies: 7 added post-SOC2 audit
    3. Stripe → Adyen migration documented across 19 facts
    [...]
```

**Demo (legal use case):**
```
Lawyer: "What did we know about the billing bug on 2025-11-15
         before the customer complained on 2025-11-20?"

GET /api/snapshot?date=2025-11-15

Returns brain state as of that date. Provides defensible evidence
of what was actually known internally — critical for deposition prep.
```

**Tier unlock:** Enterprise ($600K) — required for legal, compliance, executive reporting.
**ARR impact:** **+$80K per Enterprise customer** + **enables sales to legal/compliance/government verticals** (otherwise unreachable).
**Build cost:** ~2 weeks. Leverages Graphiti's bi-temporal model — relatively cheap.

---

## E. INSIGHTS LAYER

### E1. Belief Layer (causal hypotheses)

**Graphiti today:** Stores facts; no causal layer.

**The improvement:** Separate `beliefs.json` graph above units. DreamAgent runs on idle to propose causal hypotheses by clustering recent units. Beliefs have Bayesian confidence, half-life, support/contradict links to units.

**Demo:**
```
After 3 months of operation, DreamAgent observes:
  - 14 incident post-mortems
  - 47 deploy records
  - 23 ownership change records

Proposes belief:
  belief_b_42: "Deploys within 7 days of ownership change correlate with
                incidents at 3.2x baseline rate"
  - confidence: 0.78 (Bayesian, based on observed pairs)
  - support: [u_3104, u_3201, u_3367, ...]  (15 supporting units)
  - contradicts: [u_3098]  (1 counterexample)
  - half_life: 90d
  - last_triangulated: 2026-05-24

InquisitorAgent triggers:
  Slack DM to @sre-lead:
    "The brain has noticed a pattern: deploys within 7 days of an
     ownership change correlate with 3.2x incident rate (15 cases).
     Should this be a formal policy? (yes/no/explain)"

SRE lead: "Yes, let's add a 14-day cooldown policy after ownership changes."

System creates:
  u_5891 (kind=policy): "14-day deploy cooldown after ownership change"
  Marks belief_b_42 as "promoted to policy"

Future deploys:
  When a developer attempts deploy within 14d of ownership change,
  the brain warns: "Recent ownership change detected; cooldown policy active."
```

**Why this is a $200K/year feature:** This is the only memory system on the planet that turns *patterns* into *opinions*. Mem0/Zep/Letta/Cognee/Graphiti all just store facts. This *reasons* about facts.

**Tier unlock:** New SKU — **Insights Add-on at $15K/mo ($180K ARR)**.
**ARR impact:** **+$180K per customer** that adopts (estimated 30% adoption in Year 2 → +$54K avg across base).
**Build cost:** ~3 months. DreamAgent + TriangulationAgent + InquisitorAgent + belief schema + UI.

---

### E2. Knowledge Gap Analysis

**Graphiti today:** No gap analysis.

**The improvement:** Deterministic graph traversal that surfaces missing knowledge: "23 systems have no ownership recorded," "5 policies have no department tag," "12 entities have <2 incoming relationships."

**Demo (quarterly gap report):**
```
# Knowledge Gaps — Q1 2026

## Critical (ownership missing on production systems)
- 8 systems have NO ownership:
  payments-gateway, ml-training-pipeline, billing-export, ...
  Recommendation: assign owners via /assign-owner workflow

## High (low coverage on key entities)
- "Stripe": 47 references, only 3 facts about it
- "Compliance team": referenced 31 times, 0 process facts on file
  Recommendation: run ingestion on #compliance Slack archives

## Medium (stale facts)
- 23 gotchas haven't been verified in >365 days
- 12 ownership facts unconfirmed since reorg
  Recommendation: run /verify-stale workflow

## Knowledge coverage score: 67% (up from 54% last quarter)
```

**Tier unlock:** Drives **renewal** and **expansion** — customers see what to fix and which sources to add.
**ARR impact:** **+$60K per customer expansion** (more sources connected) + **+$30K retention** (clear renewal value).
**Build cost:** ~2 weeks. Deterministic queries over Graphiti.

---

### E3. Federated Tacit Memory (cross-org belief priors)

**Graphiti today:** Single-instance. No cross-org learning.

**The improvement:** Anonymized belief signatures aggregate across orgs. New customers query "what do other companies typically believe about X?" as priors.

**Demo:**
```
Day 1 of new customer's deployment (a fintech, 800 employees):

CEO query: "What runbook should we have for payment processor outages?"

Without federated memory:
  Brain has 0 facts. Cannot answer. Customer must build from scratch.

With federated memory:
  Federated query: anonymized signature lookup
    "kind=process, domain=payments, topic=outage_response"

  Returns 23 anonymized templates from peer orgs:
    "76% of fintechs in our base have a runbook with these phases:
     1. Confirm via external status page (Twitter, status.X.com)
     2. Activate failover to secondary processor within 5 min
     3. Notify customer success within 10 min
     4. Internal incident channel created within 2 min
     The most common ownership: SRE leads, payments engineer assists."

  Brain seeds u_1 (process), u_2 (gotcha), u_3 (ownership) as
  "imported from federated priors, please customize within 30 days"

After 30 days, customer has customized 17/23 priors, accepted 6,
declined 0. Year-1 TTV (time to value) dropped from 6 months → 3 weeks.
```

**Why this is a moat play:** Each additional customer makes the federated layer stronger → flywheel. After 100 customers, new prospects get a *qualitatively better* product than competitors offer.

**Tier unlock:** New SKU — **Federated tier at $4K/mo ($50K ARR)**, OR bundled into Enterprise.
**ARR impact:** **+$50K per customer that opts in** + **-50% TTV reduction** (faster expansion + lower churn).
**Build cost:** ~6 months. Anonymization pipeline + federated query API + privacy/legal review.

---

## 6. ARR Impact Model

### Customer Journey (1,000-person fintech, mid-market, 24 months)

| Month | Adopts | Tier | Cumulative ARR |
|---|---|---|---|
| **M0** | Starter — connect 5 sources via Airbyte | Starter | **$24K** |
| **M2** | + Typed units, FeedbackAgent, MCP tools | Professional | **$120K** |
| **M3** | + SKILLS export for engineering dept | Professional | **$120K** (drives adoption) |
| **M6** | + 3 more departments (legal, finance, sales) | Professional × 4 | **$240K** |
| **M9** | + Compliance audit, ACL, GDPR (Enterprise unlock for SOC2 prep) | Enterprise | **$600K** |
| **M12** | + Multi-modal VLM add-on | Enterprise + VLM | **$630K** |
| **M15** | + Slack-native interface (drives 5x query volume → upsell) | Enterprise | **$720K** |
| **M18** | + Insights tier (Belief Layer + Outcome-Linked) | Enterprise + Insights | **$900K** |
| **M21** | + Webhook subscriptions, knowledge gap reports | Enterprise + Insights | **$960K** |
| **M24** | + Federated Tacit Memory opt-in | Full stack | **$1,010K = $1.01M** |

**$24K → $1.01M ARR over 24 months.** That is a **42× NRR multiplier** for the cohort that adopts everything.

Realistic NRR (per Julian's target of 130%): assume only 40% of customers fully expand. Blended NRR across cohort: **~250%** over 24 months — top-quartile SaaS performance.

### At Scale: 100 Customers

| Stage | What customers have | Avg ARR | Total ARR |
|---|---|---|---|
| Today (Graphiti + Airbyte only) | Substrate | $120K | $12M |
| + Intelligence Layer (A1–A5) | Typed knowledge product | $240K | $24M |
| + Quality Layer (B1–B4) | Trustworthy answers | $320K | $32M |
| + Agent Layer (C1–C4) | Embedded in workflows | $400K | $40M |
| + Enterprise Layer (D1–D3) | F500-ready | $560K (40% on Enterprise) | $56M |
| + Insights Layer (E1–E3) | Premium SKU | $620K (30% adopt) | $62M |

**Same 100 customers, 5.2× ARR from $12M → $62M.**

### At 500 Customers (Julian's Year 3 Target)

| Scenario | ARR |
|---|---|
| Without these improvements (Julian's roadmap) | $25M |
| **With these improvements** | **$125M–$155M** |
| Exceeds $100M target by | **25–55%** |

### Unit Economics Improvement

| Metric | Today (Graphiti + Airbyte) | With Full Stack |
|---|---|---|
| CAC | $25K | $18K (better demos → higher win rate) |
| LTV | $500K | $1.5M (more tier-up, slower churn) |
| LTV/CAC | 20:1 | **83:1** |
| NRR | 130% (target) | **200%+ realistic** |
| Gross margin | 85% | 87% (SKILLS.md caching reduces inference) |
| Year-2 churn | ~15% | **~5%** (FeedbackAgent + Belief Layer create lock-in) |

---

## 7. Build Prioritization (12-Month Roadmap)

Sequenced for max ARR-per-engineering-hour.

### Quarter 1 (Months 1–3) — Foundation Port

**Goal:** Validate the Graphiti substrate works for BrainOS. Ship typed-knowledge product on top.

- ✅ Port BrainOS extraction onto Graphiti substrate
- ✅ A1 Typed Units, A2 Reconciliation Verdicts, A5 Confidence/Evidence
- ✅ B1 FeedbackAgent
- ✅ C1 MCP Tools, C2 SKILLS Export

**Engineering cost:** ~6 weeks (mostly porting work — code exists)
**ARR unlock per customer:** $120K → $240K (Professional + 1 dept expansion)

### Quarter 2 (Months 4–6) — Differentiation

**Goal:** Make the product visibly better than any competitor.

- A3 Multi-modal VLM (already built, plug in)
- A4 Department-specific extraction prompts
- B2 Knowledge Decay Scheduler
- C3 Slack-native interface

**Engineering cost:** ~8 weeks
**ARR unlock per customer:** $240K → $400K via expansion + add-ons

### Quarter 3 (Months 7–9) — Enterprise Unlock

**Goal:** Cross the F500 chasm.

- D1 Audit Log & Compliance Reports
- D2 ACL by Department
- D3 Time-Windowed Snapshots

**Engineering cost:** ~10 weeks
**ARR unlock per customer:** $400K → $700K via Enterprise tier

### Quarter 4 (Months 10–12) — Premium SKU Launch

**Goal:** Create the moat.

- B3 Active Learning Loop (Inquisitor)
- B4 Outcome-Linked Memory
- C4 Webhook Subscriptions
- E2 Knowledge Gap Analysis
- E1 Belief Layer (start — full ship Q5)

**Engineering cost:** ~12 weeks
**ARR unlock per customer:** $700K → $1M via Insights add-on + retention

### Year 2 (Months 13–24) — Moat-Building

- E1 Belief Layer (complete)
- E3 Federated Tacit Memory (new product line)
- Vertical-specific extraction (FinTech, HealthTech, GovTech)

---

## 8. Quarter 1 Engineering Plan

The most concrete, highest-ROI work. Six weeks of engineering taking the product from `$120K → $240K` average ARR per customer.

### Q1 Goal Statement

> Port BrainOS's existing intelligence layer onto Graphiti as the storage substrate. Maintain all current BrainOS functionality. Validate via test suite parity. Ship the merged stack to 1–2 design partners.

### Q1 Deliverables (in priority order)

1. **`storage/graphiti_adapter.py`** — drop-in replacement for `storage/brain.py` that persists to Graphiti+Neo4j
2. **`IngestionAgent` Graphiti-aware** — writes typed units as Graphiti edges with `kind` as edge property
3. **`StructuringAgent` Graphiti-aware** — runs reconciliation verdicts against Graphiti queries
4. **`ExecutionAgent` Graphiti-aware** — uses Graphiti hybrid retrieval instead of in-memory BM25/entity
5. **`FeedbackAgent`** — unchanged; works at answer level, substrate-agnostic
6. **`brainos_agent/tools.py`** — ports the 10 MCP tools to Graphiti backend
7. **SKILLS.md export** — query Graphiti for department-scoped distillation
8. **Test suite parity** — all existing BrainOS tests pass against Graphiti backend
9. **Migration script** — `migrate_brain_json_to_graphiti.py` for existing customers

### Sprint Plan (6 weeks)

#### Sprint 1 (Weeks 1–2) — Adapter Spike + Schema Mapping

**Goal:** Prove the storage swap works.

**Tasks:**
- Set up local Neo4j (Docker) + Graphiti Python install
- Write `storage/graphiti_adapter.py` exposing identical API to `storage/brain.py`:
  - `read_brain() → BrainState`
  - `write_unit(unit) → unit_id`
  - `write_entity(entity) → entity_id`
  - `write_relationship(rel) → rel_id`
  - `query_units(filters) → list[Unit]`
- Map BrainOS schema → Graphiti edge properties:
  - `Unit.id` → Graphiti edge UUID
  - `Unit.statement` → edge `fact` field
  - `Unit.kind` → custom edge property
  - `Unit.confidence` → custom edge property
  - `Unit.evidence` → linked Episode nodes
  - `Unit.validFrom/validTo` → Graphiti `valid_at` / `invalid_at`
  - `Unit.supersededBy` → Graphiti soft-invalidation + custom property
  - `Unit.conflictsWith` → custom edge property (Graphiti has no native concept)
- Write integration test: round-trip a unit through both backends, assert identical recall.

**Acceptance:**
- 100 units written via adapter, all readable via Graphiti directly
- Schema mapping documented in `docs/graphiti_schema_mapping.md`

**Risk:** Graphiti's Pydantic ontology may force schema constraints we don't want. **Mitigation:** start with a custom Pydantic model that mirrors BrainOS's unit schema.

---

#### Sprint 2 (Weeks 3–4) — Agent Ports

**Goal:** All four agents (Ingestion, Structuring, Execution, Feedback) work against Graphiti.

**Tasks:**

- **`agents/ingestion.py`**:
  - Change `_extract_chunk()` to call `graphiti_adapter.write_*` instead of mutating `brain.json` dict
  - VLM path (`_extract_image()`) routes through the same write path — unchanged from caller's perspective
  - Keep `EXTRACTION_SYSTEM` prompt unchanged (still produces typed units)

- **`agents/structuring.py`**:
  - Change `_reconcile()` to query Graphiti for similar existing units via embedding (Graphiti exposes hybrid search)
  - LLM verdict gate unchanged
  - Apply verdicts as Graphiti operations:
    - `supersedes` → call Graphiti's edge invalidation + write new edge with custom property `supersededBy`
    - `duplicate` → drop new unit
    - `conflicts` → write both with `disputed=true` and `conflictsWith` custom property
    - `independent` → write both, no relationship

- **`agents/execution.py`**:
  - Replace `core/indexes.py`'s in-memory BM25 + entity index with Graphiti's hybrid retrieval
  - Keep 5-signal RRF but recompute signals from Graphiti results
  - Temporal-aware reranking uses Graphiti's bi-temporal filters
  - Output format unchanged

- **`agents/feedback.py`**:
  - **No changes required** — operates on answer text + retrieved context, substrate-agnostic

**Acceptance:**
- Existing BrainOS regression tests pass against Graphiti backend
- Latency comparable (within 2x) for queries on 10K-unit test corpus
- Ingestion throughput within 2x of baseline

**Risk:** Graphiti's `add_episode()` does its own LLM extraction — we want BrainOS's typed extraction instead. **Mitigation:** call Graphiti's lower-level edge-write API directly, bypassing `add_episode()`. Need to verify this API exists.

---

#### Sprint 3 (Weeks 5–6) — Agent Surface + Migration

**Goal:** External agents can use the merged product. Existing customers can migrate.

**Tasks:**

- **`brainos_agent/tools.py`**:
  - Update each of the 10 MCP tools to query Graphiti backend
  - Tool signatures unchanged from external caller's perspective
  - Smoke-test from Claude Code: `lookup_entity`, `ask_brain`, `get_relationships`

- **`routes/skills_export.py`** (new or existing):
  - Department-scoped query over Graphiti
  - Group by `kind` (ownership, policy, gotcha, decision)
  - Render markdown
  - Smoke-test: load generated `engineering/SKILLS.md` into Cursor session

- **`scripts/migrate_brain_json_to_graphiti.py`**:
  - Read existing `brain.json`
  - For each unit/entity/relationship, call adapter write methods
  - Validate: post-migration query returns same answers as pre-migration
  - Output migration report (units migrated, conflicts encountered, etc.)

- **Documentation:**
  - Update `README.md` with Graphiti + Neo4j setup instructions
  - `docs/migration_guide.md` for existing BrainOS customers
  - `docs/graphiti_integration.md` for new deployments

**Acceptance:**
- Cursor session loads `SKILLS.md` and answers test questions correctly
- Migration script runs against a 10K-unit test brain in <10 minutes
- README setup steps work cleanly on fresh machine

**Risk:** SemanticOS may have specific Graphiti version/config requirements that conflict with BrainOS's. **Mitigation:** coordinate Graphiti version with Julian before Sprint 1 starts.

---

### Files to touch (BrainOS repo)

**New files:**
- `src/python_backend/storage/graphiti_adapter.py`
- `src/python_backend/scripts/migrate_brain_json_to_graphiti.py`
- `docs/graphiti_schema_mapping.md`
- `docs/migration_guide.md`
- `docs/graphiti_integration.md`

**Modified files:**
- `src/python_backend/storage/brain.py` — keep as deprecated; emit warning if used
- `src/python_backend/storage/chroma.py` — keep as fallback; new deployments skip it
- `src/python_backend/agents/ingestion.py` — write path swap
- `src/python_backend/agents/structuring.py` — read+write path swap
- `src/python_backend/agents/execution.py` — retrieval swap
- `src/python_backend/agents/feedback.py` — unchanged
- `src/python_backend/core/indexes.py` — replaced by Graphiti hybrid retrieval (keep file as deprecated)
- `src/python_backend/brainos_agent/tools.py` — backend swap
- `src/python_backend/brainos_agent/retrieval_tools.py` — backend swap
- `src/python_backend/requirements.txt` — add `graphiti-core`, `neo4j`
- `README.md` — Graphiti+Neo4j setup
- `docker-compose.yml` — add Neo4j service

**Unchanged:**
- `agents/feedback.py`
- All frontend (`src/app/*`)
- `clients/router.py`, `clients/vllm.py`, `clients/claude.py`
- All prompts (`agents/prompts.py`, `brainos_agent/prompts.py`)

### Test Plan

1. **Unit tests** — adapter round-trip, schema mapping correctness
2. **Integration tests** — full ingest → structure → execute → feedback pipeline on test corpus
3. **Regression tests** — existing BrainOS test suite must pass against Graphiti backend
4. **Performance tests** — ingest throughput, query latency at 10K, 100K, 1M units
5. **Migration tests** — migrate existing `brain.json`, validate query parity
6. **End-to-end** — Cursor session loads `SKILLS.md` and answers correctly via MCP tools

### Migration Strategy

**For existing BrainOS deployments:**
1. Deploy new version with both `brain.json` and Graphiti backends supported
2. Run `migrate_brain_json_to_graphiti.py` in shadow mode (write to both)
3. Validate query parity for 1 week
4. Cutover: read+write to Graphiti only
5. Archive `brain.json` as backup

**For new deployments:**
- Graphiti-only from day one
- `brain.json` path removed from setup docs

### Engineering Resourcing

**Two engineers full-time for 6 weeks** OR **one engineer for 12 weeks**. The work parallelizes well:
- Engineer 1: Storage adapter + migration (Sprints 1 + 3)
- Engineer 2: Agent ports + retrieval (Sprints 2 + 3)

### Definition of Done

- All BrainOS regression tests pass against Graphiti backend
- Migration script tested on a real (not synthetic) brain
- One design partner running on the merged stack in production
- Query latency within 2x of baseline at 10K-unit corpus
- README + migration docs reviewed by Julian for SemanticOS-side compatibility

---

## 9. Key Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Graphiti API doesn't expose low-level edge writes (forces use of `add_episode` LLM extraction) | Medium | High | Sprint 1 spike validates this before committing further |
| Brand collision (SemanticOS vs BrainOS) | High | Medium | Defer brand conversation until after first joint demo |
| SemanticOS's "production-ready" claim doesn't hold | Medium | High | Request live demo with real customer data before Q1 commits |
| Graphiti's roadmap diverges from our needs | Low | High | Contribute upstream where possible; maintain fork as fallback |
| Julian wants equity/control terms that don't work for BrainOS | Medium | High | Run Model B (interop partnership) before discussing Model A (merger) |
| Customer migration breaks production for existing BrainOS users | Medium | High | Shadow-mode dual-write for 1 week before cutover |
| Neo4j operational complexity scares off design partners | Low | Medium | Use FalkorDB (lighter) for SMB deployments; reserve Neo4j for Enterprise |
| Graphiti's bi-temporal model conflicts with BrainOS's `temporalStatus` enum | Medium | Low | Map BrainOS enum as computed property on Graphiti edges |

---

## 10. Open Questions for Julian

These must be answered before committing to Model A (full integration):

1. **What does the current SemanticOS architecture look like?** The Sep 2025 doc is 8 months old; Julian flagged Skills + "other things now play in our favor." Need current diagram.

2. **Is the production pipeline running on real customer data?** "Production-ready" claim deserves verification.

3. **Which Graphiti version are you on, and what's your contingency if the roadmap diverges?** Both stacks would inherit that coupling.

4. **What's the smallest joint demo we can ship in 2 weeks?** Spike before deciding on equity/brand/team.

5. **Where do you sit on YC?** If applied, when do you hear back? Affects timing of any merge conversation.

6. **How does your Skills concept differ from BrainOS's SKILLS.md export?** Convergent evolution is interesting — alignment likely close.

7. **What customer count are you at? What's your current ARR?** Affects who has leverage in any structural conversation.

8. **What does Julian's team look like?** Engineering capacity affects sprint planning.

---

## 11. Next Steps

### Immediate (this week)
- [ ] Share this document with Julian
- [ ] Schedule 60-min working session with Julian for architecture walkthrough
- [ ] Internal alignment with BrainOS co-founder on Model A vs Model B preference

### Within 2 weeks
- [ ] Run Sprint 1 spike (Graphiti adapter) — validate technical feasibility
- [ ] Get answers to all 8 questions in §10
- [ ] Decide between Model A (full integration), Model B (interop), or Model C (co-position)

### Within 30 days
- [ ] If Model A approved: complete Sprint 2 (agent ports)
- [ ] Identify first joint design partner (could be existing BrainOS customer or SemanticOS prospect)
- [ ] Joint Vector Space Day presence on 2026-06-11 — opportunity to soft-launch the collaboration narrative

### Within 90 days (end of Q1)
- [ ] Complete Q1 engineering plan (§8)
- [ ] One design partner running on merged stack
- [ ] Updated pitch deck reflecting merged value proposition
- [ ] Decision point on brand, equity, and corporate structure

---

## Appendix: Suggested First Reply to Julian

> Julian, thanks for sending this — and for the gentle Graphiti correction, which landed. You're right; I had it framed as a peer rather than a framework, and that was the wrong lens. The clearer picture for me now is that SemanticOS and BrainOS sit at *different layers* of what's actually the same OS — your stack (Airbyte → Kafka → Graphiti → Neo4j → MCP) is the substrate; ours (typed units, reconciliation verdicts, VLM extraction, FeedbackAgent, SKILLS export, agent tools) is the cognitive layer on top.
>
> I wrote up a longer strategy doc thinking through how the merged stack could ladder from $120K to $1M ARR per customer over 24 months, with a Q1 engineering plan to validate the integration. Sharing it here — would love your take, especially on (a) whether the layer-mapping matches how you think about SemanticOS today, and (b) whether the Q1 engineering scope is feasible from your side.
>
> Two specific questions before we dig deeper:
>
> 1. **What does your current architecture look like?** Your doc is from Sep 2025 and you mentioned Skills + "other things that now play in our favor" — I'd love to see where you've taken it.
> 2. **What does an MVP integration look like for you?** If we ran BrainOS's IngestionAgent + StructuringAgent + FeedbackAgent on top of SemanticOS's normalized Kafka stream — writing to Graphiti/Neo4j instead of our own JSON+Chroma — what's the smallest demo that would let us see the joint thing working end-to-end? Happy to spike this from our side.
>
> Worth a working session before the next meeting. Vector Space Day on June 11 might also be a good forcing function if you're going to be there.
