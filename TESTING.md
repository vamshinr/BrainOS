# BrainOS — Testing Guide

Full end-to-end test cases with mock inputs, expected backend behaviour, and
expected UI output. Run the Python backend first (`uvicorn main:app --port 8081`)
and the Next.js dev server (`npm run dev`), then work through each section.

---

## 0. Pre-flight checks

```bash
# Python backend health check
curl http://localhost:8081/health
```

Expected response:
```json
{
  "status": "ok",
  "gpu_backend": "AMD MI300X via vLLM",
  "model": "<actual model name from vLLM>",
  "vlm_model": "<actual vlm model>",
  "available_models": ["<list of served models>"],
  "chroma_units": 0,
  "brain_json": false
}
```

If `available_models` is empty the vLLM endpoint is unreachable.
If `model` differs from `.env MODEL_NAME`, `_resolve_model()` auto-corrected it
and printed a warning — update `.env` to silence the warning.

---

## 1. Text Ingestion — Ownership + Relationship extraction

### Input (paste into Ingest → Text/Paste tab)

**Kind:** Slack  
**Title:** `#billing-team — ownership thread`  
**Content:**
```
Alice Chen owns the billing service end-to-end. She reports to Bob Martinez, 
the VP of Engineering. The billing service uses Stripe as the payment processor 
and integrates with our internal Ledger API for reconciliation. The billing team 
is responsible for all PCI compliance requirements.
```

### Expected Python backend log
```
[IngestionAgent] Extraction: 5-7 units, 5+ entities
[StructuringAgent] Upserted 5-7 vectors to ChromaDB
[StructuringAgent] Reconciled: 0 superseded (fresh brain)
[StructuringAgent] 3-5 relationships stored
```

### Expected API response (`POST /api/ingest`)
```json
{
  "message": "Ingested and structured via 70B model + ChromaDB.",
  "source_id": "<8-char uuid>",
  "units_extracted": 5,
  "entities_extracted": 5,
  "relationships_extracted": 4,
  "units_stored": 5,
  "units_superseded": 0,
  "entities_stored": 5,
  "relationships_stored": 4,
  "chroma_total": 5,
  "brain_totals": { "sources": 1, "entities": 5, "units": 5, "relationships": 4 }
}
```

### Expected entities extracted
| Name | Kind |
|------|------|
| Alice Chen | person |
| Bob Martinez | person |
| billing service | system |
| Stripe | tool |
| Ledger API | system |
| billing team | team |

### Expected knowledge units
| Kind | Statement |
|------|-----------|
| ownership | Alice Chen owns the billing service end-to-end |
| ownership | Bob Martinez is the VP of Engineering |
| fact | The billing service uses Stripe as the payment processor |
| fact | The billing service integrates with the Ledger API for reconciliation |
| policy | The billing team is responsible for all PCI compliance requirements |

### Expected relationships
| From | Relation | To |
|------|----------|----|
| Alice Chen | owns | billing service |
| Alice Chen | reports-to | Bob Martinez |
| billing service | uses | Stripe |
| billing service | integrates-with | Ledger API |

### Expected UI
- Home page: Sources=1, Entities=6, Relationships=4, Knowledge units=5
- Graph page: 6 nodes connected by 4 directed arrows with labels
- Clicking "Alice Chen" node shows: `→ owns billing service`, `→ reports-to Bob Martinez`

---

## 2. Text Ingestion — Policy + Reconciliation

After test 1, ingest a second source that overlaps:

**Kind:** Doc  
**Title:** `Engineering handbook — billing service ownership`  
**Content:**
```
The billing service is owned by the Platform team, led by Carol Davis.
Alice Chen is the primary on-call engineer for billing.
All PRs to billing-svc require 2 approvals from the billing team.
The billing service is deployed on AWS us-east-1.
```

### Expected reconciliation behaviour
The unit "Alice Chen owns the billing service" (from test 1) and the new unit
"The billing service is owned by the Platform team" are about the same subject
with conflicting ownership. The StructuringAgent should call the LLM reconciler.

Expected verdict: **supersedes** — the more specific new doc's ownership unit
marks the old "Alice Chen owns billing service" unit as stale.

### Expected API response
```json
{
  "units_extracted": 4,
  "units_stored": 4,
  "units_superseded": 1,
  "relationships_extracted": 2,
  "relationships_stored": 2
}
```

### Expected UI
- Home page: Superseded count increases by 1
- The old ownership unit disappears from "Recent knowledge" (it's stale)
- Graph page: "Platform team" and "Carol Davis" appear as new nodes

---

## 3. File Upload — PDF / Markdown

### Input
Upload a markdown file with this content (save as `runbook.md`):

```markdown
# Incident Runbook — P0 Outages

## Definition
P0 = customer-impacting outage affecting >100 users or >$10k/hour revenue impact.

## On-call rotation
The SRE team owns incident response. Dave Park is the current on-call lead.
PagerDuty alerts fire to #incidents Slack channel first.

## Escalation path
1. On-call SRE acknowledges within 5 minutes
2. If unresolved in 15 minutes, escalate to engineering manager
3. Carol Davis (VP Eng) is the exec escalation contact for P0s

## Stripe webhook gotcha
If the Stripe webhook signature header is missing, the handler silently drops
the event — no error logged. Always check CloudWatch for missing signature errors.
```

**Kind:** Doc  
**Title:** `Incident Runbook v2`

### Expected extraction
| Kind | Statement |
|------|-----------|
| definition | P0 = customer-impacting outage affecting >100 users or >$10k/hour |
| ownership | The SRE team owns incident response |
| ownership | Dave Park is the current on-call lead |
| process | On-call SRE must acknowledge a P0 within 5 minutes |
| process | Escalate to engineering manager if unresolved in 15 minutes |
| ownership | Carol Davis is the exec escalation contact for P0s |
| gotcha | Stripe webhook handler silently drops events when signature header is missing |

### Expected relationships
| From | Relation | To |
|------|----------|----|
| SRE team | owns | incident response |
| Dave Park | manages | on-call rotation |
| Carol Davis | governs | P0 escalation |
| Stripe | integrates-with | webhook handler |

### Expected UI
- File upload tab shows "✓ Ingested 7 units from runbook.md"
- Graph page: "SRE team", "Dave Park", "Carol Davis", "PagerDuty" appear as nodes
- Clicking "Stripe" shows all Stripe-related units (from both test 1 and test 3)

---

## 4. Ask / Execution Agent

### Test 4a — Well-grounded answer

**Question:** `Who owns the billing service?`

**Expected flow:**
1. Query embedded → ChromaDB top-6 retrieved
2. Retrieved docs contain ownership units about billing service
3. 70B model generates grounded answer

**Expected answer (approximate):**
> "The billing service is owned by the Platform team, led by Carol Davis. Alice Chen
> is the primary on-call engineer for billing."

**Expected metadata:**
- Latency: 500–4000 ms (AMD MI300X)
- Retrieved: 3–6 units
- Feedback: Grounded ✓, confidence ≥ 0.85

### Test 4b — Partial knowledge gap

**Question:** `What is our SLA for enterprise customers?`

**Expected answer:**
> "The company brain does not contain specific SLA commitments for enterprise
> customers. The ingested knowledge covers incident response runbooks and billing
> ownership, but no enterprise SLA document has been ingested."

**Expected metadata:**
- Feedback: Ungrounded ✗, confidence ≤ 0.45
- This is the "gap detection" demo moment — the system knows what it doesn't know

### Test 4c — Gotcha knowledge

**Question:** `What should I watch out for with Stripe webhooks?`

**Expected answer:**
> "The Stripe webhook handler silently drops events when the signature header is
> missing — no error is logged. Always check CloudWatch for missing signature errors."

**Expected metadata:**
- Unit kind used: "gotcha"
- Feedback: Grounded ✓, confidence ≥ 0.90

### Test 4d — Process question

**Question:** `What's the escalation path for a P0 outage?`

**Expected answer:**
Structured steps matching the runbook: 5 min acknowledge → 15 min escalate to
manager → Carol Davis for exec escalation.

---

## 5. GPU Metrics Dashboard

Navigate to `/metrics`.

### Expected when vLLM is reachable

| Field | Expected value |
|-------|---------------|
| Status dot | Green (Prometheus live) |
| Generation tok/s | > 0 after any ask |
| Total requests | Increments with each `/api/ask` call |
| GPU KV-cache | Progress bar fills as requests run |
| Embedding backend | "CPU · sentence-transformers · all-MiniLM-L6-v2" |

### Expected when Prometheus is unreachable

| Field | Expected value |
|-------|---------------|
| Status dot | Amber |
| Generation tok/s | — (dash) |
| Total requests | 0 |
| Message | "Prometheus unreachable — live tok/s and latency unavailable" |

**Why Total requests showed 0 (was a bug — now fixed):**  
vLLM's `request_success_total` metric has labels:
```
vllm:request_success_total{finished_reason="stop"} 12
vllm:request_success_total{finished_reason="abort"} 1
```
The old parser kept only the last value (1). The fixed parser **sums** all
label variants, giving the correct total (13).

---

## 6. Knowledge Graph / Map page

Navigate to `/graph`.

### Expected after tests 1–3

**Nodes visible:** Alice Chen, Bob Martinez, billing service, Stripe, Ledger API,
billing team, Platform team, Carol Davis, SRE team, Dave Park, PagerDuty, ...

**Directed edges (labeled):**
- Alice Chen →owns→ billing service
- Alice Chen →reports-to→ Bob Martinez
- billing service →uses→ Stripe
- billing service →integrates-with→ Ledger API
- SRE team →owns→ incident response
- Carol Davis →governs→ P0 escalation

**Graph legend:** shows "Knowledge graph — directed relationships"  
(If no explicit relationships yet, shows "Co-mention graph" as fallback)

**Relationship index table** below the graph lists all edges with confidence scores.

### What makes this NOT just RAG

| Plain RAG | BrainOS Knowledge Graph |
|-----------|------------------------|
| Returns text chunks similar to query | Returns grounded answer WITH source units |
| No structure between entities | Explicit `owns`, `uses`, `governs` edges |
| Can't answer "who does Alice report to?" | Traverses graph: Alice →reports-to→ Bob |
| Can't show ownership chains | Graph visualizes full org/system topology |
| Re-embeds same knowledge each time | Reconciles: supersedes stale ownership |

---

## 7. Clear and re-seed

### Full clear
`DELETE /api/state?all=true`

Expected: ChromaDB collection dropped+recreated, brain.json reset to `{}`, 
in-memory Next.js cache invalidated. Home page shows 0 across all stats.

### Seed button
Click "Seed with example company" on the empty home page.

Expected: 5 seed sources ingested one by one (NDJSON progress stream), 
each processed by IngestionAgent + StructuringAgent on the AMD MI300X.
After seeding: ~25–40 knowledge units, ~15 entities, ~10 relationships.

---

## 8. Brain.json vs ChromaDB — what each does

| | brain.json | ChromaDB |
|--|-----------|----------|
| **Written by** | Python StructuringAgent | Python StructuringAgent |
| **Read by** | Next.js home/graph/skills pages | Python ExecutionAgent only |
| **Contains** | Full structured state: sources, entities, units, relationships | Vector embeddings (float arrays) + minimal metadata |
| **Used for** | Dashboard rendering, graph visualization, skills export, reconciliation audit trail | Semantic similarity search (find top-6 units similar to a query) |
| **Human readable** | Yes — open `data/brain.json` to inspect | No — binary HNSW index |
| **Queryable without LLM** | Yes — filter by kind, entity, source | No — requires embedding a query first |

**Short answer:** brain.json is the knowledge base you can read and reason about.
ChromaDB is the search index that makes retrieval fast. Both are written
atomically by the same StructuringAgent call so they stay in sync.

---

## 9. Curl-based smoke tests

```bash
# Ingest
curl -s -X POST http://localhost:8081/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"kind":"slack","title":"Test","content":"Dave owns the search service. Search uses Elasticsearch."}' \
  | jq '{units_stored, relationships_stored}'

# Ask
curl -s -X POST http://localhost:8081/api/ask \
  -H "Content-Type: application/json" \
  -d '{"query":"Who owns the search service?"}' \
  | jq '{answer, used, latency_ms}'

# Metrics
curl -s http://localhost:8081/api/metrics | jq '{gpu: .gpu.prometheus_reachable, units: .knowledge.units, rels: .knowledge.relationships}'

# Delete single unit (get an id from brain.json first)
curl -s -X DELETE http://localhost:8081/api/units/<unit_id>

# Full clear
curl -s -X DELETE http://localhost:8081/api/clear
```

---

## 10. Known limitations for demo

1. **Reconciliation fires only for same-kind units from different sources** — two
   ownership units from the same source won't reconcile against each other.

2. **Relationship deduplication** is exact-match on (from, relation, to) — if
   the LLM phrases the same relationship differently across two ingests, both
   edges appear in the graph.

3. **ChromaDB is eventually consistent with brain.json** — if the Python process
   crashes mid-write, brain.json and ChromaDB may diverge. Run `/api/clear` and
   re-ingest to reset.

4. **GPU embeddings require a separately served model** — set `EMBEDDING_API_BASE`
   in `.env` and start a second vLLM instance serving `BAAI/bge-large-en-v1.5`.
   Default is CPU sentence-transformers.



# More testings

  ---
  Doc 1 — upload first (establishes the baseline)
  Acme Engineering Runbook v1.2

  Alice Chen owns billing-svc end-to-end. She is the primary on-call contact for all
  payment-related incidents.

  Bob Martinez owns auth-svc and the API gateway. He joined the team in January 2024.
  
  The billing-svc runs on AWS us-east-1 inside the payments VPC. It depends on auth-svc
  for token validation before processing any charge.
  
  We chose Stripe over Adyen for v2 payments because Stripe had better EU coverage and
  lower transaction fees for our volume.

  P0 is defined as a customer-impacting outage affecting more than 5% of active users.
  
  All production PRs require 2 reviewers before merge. Exceptions must be approved by
  an engineering director.
  
  GOTCHA: The Stripe webhook handler silently drops events when the Stripe-Signature
  header is missing. No error is logged. This has caused billing sync failures twice.

  The deployment process for billing-svc: merge to main, wait for CI to pass, tag a
  v-prefix release (e.g. v2.4.1), then the release pipeline auto-deploys to staging
  first and production after a 10-minute soak.

  ---
  Doc 2 — upload second (tests supersede on ownership + policy update)
  Acme Org Update — May 2026
  
  Effective immediately, Bob Martinez has taken over billing-svc from Alice Chen.
  Alice is moving to the infrastructure team. Bob now owns both billing-svc and auth-svc.
  
  Following the incident last quarter, the PR review policy has been updated. All
  production PRs now require 3 reviewers before merge, not 2. Security-sensitive changes
  require an additional sign-off from the security team.
 
  The deployment soak time for billing-svc has been extended from 10 minutes to 30
  minutes after two regressions slipped through in Q1.
  Expect: Bob owns billing-svc supersedes Alice owns billing-svc. 3 reviewers supersedes 2 reviewers. 30 min soak supersedes 10 min soak.

  ---
  Doc 3 — upload third (tests conflict/dispute)
  Engineering Wiki — Service Ownership (last edited by Carol Nguyen)
  
  billing-svc is owned by Carol Nguyen. She has been maintaining it since the
  restructuring in April. 

  auth-svc is owned by David Kim. David took over from Bob Martinez earlier this year.
  Expect: Carol owns billing-svc conflicts with Bob owns billing-svc (no clear temporal signal). David owns auth-svc should supersede Bob owns 
  auth-svc.

  ---
  Doc 4 — tests future + historical temporal
  Acme Q3 2026 Planning Notes
  
  We used to use Adyen for payments processing before we migrated to Stripe in early 2024.
  The Adyen integration is fully decommissioned.
  
  Starting September 1 2026, the legacy monolith billing module will be deprecated and
  replaced by billing-svc entirely. Teams should migrate any direct calls to the monolith
  before that date.

  Effective 2026-07-01, Carol Nguyen will transfer ownership of billing-svc to the new
  Platform team, led by Priya Shah. Until then Carol remains the owner.

  The Python 2 compatibility layer in auth-svc will be removed by end of Q3 2026.
  Expect: Adyen → historical. Monolith deprecation → future. Carol → Platform team transfer → future with valid_from. Python 2 removal → future.

  ---
  Doc 5 — tests duplicate detection
  Acme Internal FAQ
  
  Q: What is our incident severity definition?
  A: A P0 incident is a customer-facing outage impacting more than 5 percent of active
  users. P1 is degraded performance affecting less than 5 percent.

  Q: Which payment processor do we use?
  A: The company standardized on Stripe for all subscription billing following an
  evaluation in 2024. We previously evaluated Adyen but chose Stripe due to better
  EU coverage.
  
  Q: Where does billing-svc run?
  A: billing-svc is deployed on Amazon Web Services in the us-east-1 region.
  Expect: P0 definition, Stripe decision, billing-svc location all flagged as duplicates of Doc 1 units.

  ---
  Doc 6 — tests entity canonicalization + relationship graph
  Acme Vendor & Integration Map
  
  Stripe Inc. (also referred to as Stripe Payments and simply Stripe) is our primary
  payment processor. billing-svc integrates with Stripe via webhook and REST API.

  Amazon Web Services (AWS) hosts the majority of our infrastructure. auth-svc,
  billing-svc, and the API gateway all run on AWS. We use AWS us-east-1 as the
  primary region.

  PagerDuty is used for on-call alerting. billing-svc and auth-svc both report
  incidents to PagerDuty. The on-call rotation is managed by Bob Martinez.

  Datadog is used for observability across all services. The billing-svc dashboard
  in Datadog is the canonical source of truth for payment success rates.

  GitHub is the code repository for all engineering projects. All services use
  GitHub Actions for CI/CD pipelines.
  Expect: "Stripe Inc.", "Stripe Payments", "Stripe" collapsed into one canonical entity. Rich relationship graph: billing-svc integrates_with 
  Stripe, billing-svc depends_on auth-svc, etc.