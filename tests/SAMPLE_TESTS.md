# Mnemosyne — Capability Tests

Hands-on test scenarios that demonstrate, end to end, what this engine does that a
semantic-search memory cannot. Each test is self-contained: a paste-able input, the
exact API call (or UI step), the expected behavior, and the capability it proves.

> **Scope.** These are *manual acceptance / demo scenarios* run against a live stack.
> The automated unit/integration suite lives in `mnemosyne/tests/` (pytest, runs against
> real Neo4j + Qdrant) — run it with `python -m pytest mnemosyne/tests -v`.

> **Honest framing.** Causality here is *approximate* — temporal precedence (hard
> invariant) + semantic association (embedding cosine) + a batched LLM judgment — not
> true causal inference. Expected confidences below are typical ranges, not exact
> values; LLM-generated text varies between runs.

---

## 0. Prerequisites

```bash
./scripts/start.sh        # Neo4j :7474/:7687 · Qdrant :6333 · API :8090 · UI :3000
curl -s localhost:8090/health   # expect {"status":"ok", "neo4j":"connected", ...}
```

`.env` needs `NEO4J_PASSWORD` and `ANTHROPIC_API_KEY` (extraction + causal judgment are
real Haiku calls). Start every session from a clean slate:

```bash
curl -s -X POST localhost:8090/reset    # destructive: wipes events + edges
```

---

## Capability matrix

| # | Capability | Test |
|---|---|---|
| 1 | Event extraction with relative-time resolution | CT-1 |
| 2 | Causal edge inference — 3 signals, one batched LLM call per event | CT-2 |
| 3 | "Why did X happen?" — root-cause chain, time-ordered | CT-3 |
| 4 | Distractor exclusion (the proof vs. semantic search) | CT-3 |
| 5 | Associative baseline, for contrast | CT-4 |
| 6 | Forward traversal — consequences, not just causes | CT-5 |
| 7 | Cross-domain generality (business events, no keyword lists) | CT-6 |
| 8 | Consolidation — duplicates reinforce instead of duplicating | CT-7 |
| 9 | Temporal-precedence invariant (cause must precede effect) | CT-8 |
| 10 | Operator-asserted edges | CT-9 |
| 11 | Large-document chunking + async job queue with live progress | CT-10 |

---

## CT-1 — Event extraction + relative-time resolution

**Capability:** raw prose in, discrete timestamped events out. Relative times ("this
morning", "20 minutes later") are resolved against a reference time.

**Input** (note: no absolute timestamps anywhere):

```bash
curl -s -X POST localhost:8090/ingest -H 'Content-Type: application/json' -d '{
  "text": "This morning at nine the payments team enabled the new fraud-scoring model. About twenty minutes later, transaction approval latency doubled. By ten oclock, the on-call engineer had rolled the model back to the previous version.",
  "source_id": "ct1-relative-times",
  "reference_time": "2026-06-10T17:00:00Z"
}'
```

**Expected:**
- `counts.created` ≈ 3 (one per happening; exact segmentation is the model's call).
- `GET /graph` shows the events with **absolute ISO timestamps** on 2026-06-10
  (~09:00, ~09:20, ~10:00 UTC) — derived from the reference time, not copied from text.
- Each event has a one-line `summary` and lowercase entity `tags`
  (e.g. `fraud-scoring`, `payments`, `latency`).

---

## CT-2 — Causal edge inference (three signals, bounded LLM cost)

**Capability:** for each ingested event, the top-K most-associated prior events within
the temporal window are selected by embedding cosine and judged in **one batched Haiku
call** — confidence = `0.3·temporal + 0.2·association + 0.5·llm`.

**Steps:** after CT-1, inspect the edges:

```bash
curl -s localhost:8090/graph | python3 -m json.tool
```

**Expected:**
- Edges exist: model-enabled → latency-doubled and model-enabled → rollback (relations
  like `led_to` / `triggered`). On this deliberately terse input, blended confidences
  land **near the 0.55 threshold (measured: 0.52–0.56)** — short summaries embed far
  apart, so the association signal is weak. Confidence tracks input richness: the full
  incident narrative in CT-3 scores **0.57–0.86** on the same scorer.
- Every edge's `evidence` field shows all three signals plus the judge's one-sentence
  justification, e.g. `temporal=0.79; association=0.62; llm=0.99: <justification>`.
- `method` is `temporal+association+llm`.
- Edges below the threshold (including any the judge rates `none`) still appear in
  `/graph` — stored for auditability, **excluded from default traversal**.

---

## CT-3 — "Why did X happen?" with distractor exclusion (the flagship)

**Capability:** answering *why* by walking the causal graph backward to root cause —
while explicitly excluding events that are semantically similar but causally irrelevant.

**Input:** ingest the bundled incident narrative. It contains the real causal chain
(cache-TTL change → hit-rate collapse → DB-pool saturation → checkout 500s → rollback →
recovery) **plus two deliberate distractors** that share its vocabulary: a cache-warming
cron note (3 weeks earlier) and a checkout-redesign design doc (4 months earlier).

```bash
python3 - <<'EOF'
import json, urllib.request
text = open("examples/sample_ingest.txt").read()
req = urllib.request.Request(
    "http://localhost:8090/ingest",
    json.dumps({"text": text, "source_id": "incident-demo",
                "reference_time": "2026-06-04T16:00:00Z"}).encode(),
    {"Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode()[:400])
EOF
```

**The question:**

```bash
curl -s -X POST localhost:8090/retrieve -H 'Content-Type: application/json' -d '{
  "query": "Why did checkout start throwing 500s this afternoon?",
  "mode": "causal", "k": 6
}' | python3 -m json.tool
```

**Expected:**
- `anchor_event_id` = the 14:19 checkout-500s event.
- `chain` is **time-ordered from root cause to outcome**: the 14:02 TTL config change
  first (`incoming_relation: null` — the root), then hit-rate collapse, DB-pool
  saturation, checkout 500s; each later entry carries its `incoming_relation` and
  `confidence`.
- `answer` is a 2–5 sentence narrative citing event ids and timestamps.
- **`excluded_distractors` contains the cache-warming cron and the checkout-redesign
  doc** — both matched the query semantically, neither sits on any causal path. This
  field is the demonstrable difference from a vector-search memory.

---

## CT-4 — Associative baseline (the failure mode, for contrast)

**Capability under test:** the contrast itself — what every embedding-only memory
returns for the same question.

```bash
curl -s -X POST localhost:8090/retrieve -H 'Content-Type: application/json' -d '{
  "query": "Why did checkout start throwing 500s this afternoon?",
  "mode": "associative", "k": 4
}' | python3 -m json.tool
```

**Expected:**
- Response is `{mode, query, chunks}` — flat top-k by cosine similarity, no ordering,
  no synthesized answer.
- **The root cause (the 14:02 TTL change) is typically missing entirely** — it shares
  few words with the question, so similarity ranks it below the symptom events
  (measured: top-4 = alert, recovery, pool saturation, hit-rate collapse; no root
  cause). On sparser corpora the keyword-overlapping distractors surface in top-k too.
- Demo line: run CT-3 and CT-4 side by side in the UI (`/ask` has both modes).

---

## CT-5 — Forward traversal (consequences)

**Capability:** the graph walks forward too — "what happened as a result," not only
"what caused this."

**Steps:** in the CT-3 response, look past the anchor.

**Expected:** the 14:41 rollback and 14:55 recovery events appear in the chain *after*
the checkout-500s anchor (reached via outgoing edges), so a single query yields
root cause → incident → resolution. Set `FORWARD_TRAVERSAL=false` in `.env` (and
restart the backend) to disable, then re-verify they disappear.

---

## CT-6 — Cross-domain generality (business events, not ops)

**Capability:** nothing in the scorer is incident- or English-marker-specific — the
association signal is an embedding cosine, so causal inference transfers to any domain.

> **Timescale knob (required for this test).** Candidate causes are gated by a temporal
> lookback window, default **6 hours** (`TEMPORAL_MAX_WINDOW_S=21600`) — tuned for
> incident timelines. Business events sit days apart, so with the default window this
> input yields `counts.edges == 0` (measured) — the temporal gate working as designed,
> at the wrong scale. For business-scale data set in `.env` and restart the backend:
>
> ```bash
> TEMPORAL_MAX_WINDOW_S=2592000   # 30-day lookback
> TEMPORAL_TAU_S=604800           # 7-day decay half-life
> ```

**Input:**

```bash
curl -s -X POST localhost:8090/ingest -H 'Content-Type: application/json' -d '{
  "text": "[2026-04-01 09:00] Pricing update shipped: Pro plan raised from $49 to $79 per month, applying to existing customers at renewal. [2026-04-03 11:30] Support ticket volume doubled; most tickets cite the higher price on renewal invoices. [2026-04-08 16:00] Acme Corp paused its enterprise contract negotiation, naming the new pricing as the reason. [2026-04-15 10:00] Monthly churn for Pro seats hit 9.4 percent, up from 3.1 percent, driven by renewal sticker shock. [2026-04-18 14:00] A win-back discount campaign launched for churned Pro customers. Unrelated note from February: [2026-02-12 10:00] Competitor FooCorp announced their own price increase for premium plans.",
  "source_id": "pricing-demo"
}'
```

**The question:**

```bash
curl -s -X POST localhost:8090/retrieve -H 'Content-Type: application/json' -d '{
  "query": "Why did Pro churn spike in April?", "mode": "causal", "k": 6
}' | python3 -m json.tool
```

**Expected:**
- Chain rooted at the **pricing update**, flowing through ticket volume / lost
  negotiation into the churn spike; the win-back campaign appears as a forward
  consequence.
- The FooCorp competitor announcement — high keyword overlap ("price increase",
  "plans") — lands in `excluded_distractors`, **without any English causal-marker
  list in the code**: the same three signals did the work on business events.

---

## CT-7 — Consolidation: reinforcement instead of duplication

**Capability:** near-duplicate observations strengthen an existing memory rather than
creating a second copy (`reinforcement_count`), and `salience` decays with age unless
reinforced.

**Steps:** ingest the same fact twice, a minute apart:

```bash
for i in 1 2; do curl -s -X POST localhost:8090/ingest -H 'Content-Type: application/json' -d '{
  "text": "At 09:00 today the build pipeline was switched from Jenkins to Buildkite.",
  "source_id": "dup-test", "reference_time": "2026-06-10T12:00:00Z"
}'; echo; done
```

**Expected:**
- First call: `counts.created == 1`. Second call: `counts.created == 0`,
  `counts.reinforced == 1`, and `events_reinforced[0].reinforcement_count == 1`.
- `GET /graph` shows **one** event for the switch, not two; its `salience` is 1.0 (fresh)
  and decays over time for unreinforced events (half-life `SALIENCE_HALF_LIFE_S`, 7 days).

---

## CT-8 — The temporal invariant (cause must precede effect)

**Capability:** `cause.occurred_at ≤ effect.occurred_at` is a hard invariant, enforced
even on operator-asserted edges — the engine refuses to store a back-in-time cause.

**Steps:** take two event ids from `GET /graph` where A occurred *after* B, then:

```bash
curl -s -i -X POST localhost:8090/edge -H 'Content-Type: application/json' -d '{
  "cause_id": "<LATER_EVENT_ID>", "effect_id": "<EARLIER_EVENT_ID>",
  "relation": "caused", "confidence": 0.9, "evidence": "should be rejected"
}'
```

**Expected:** **HTTP 422** with a `CausalityViolation` detail naming both timestamps.
No edge is created (re-check `/graph`).

---

## CT-9 — Operator-asserted edges

**Capability:** humans can assert causality the inference missed; asserted edges carry
`method: "manual"` and full provenance like every other edge.

```bash
curl -s -X POST localhost:8090/edge -H 'Content-Type: application/json' -d '{
  "cause_id": "<EARLIER_EVENT_ID>", "effect_id": "<LATER_EVENT_ID>",
  "relation": "enabled", "confidence": 0.95, "evidence": "post-incident review finding"
}'
```

**Expected:** 200 with the created edge; it participates in causal traversal
immediately (re-run the relevant CT-3/CT-6 query and see the chain change).

---

## CT-10 — Large documents: chunking + async job queue

**Capability:** large files are chunked with a sliding context window (no truncation),
ingested as a background job with live progress over SSE — the UI stays responsive.

**Steps (UI):** open `localhost:3000/ingest`, paste or upload a document well over
`CHUNK_MAX_CHARS` (12k chars — e.g. a long postmortem or meeting transcript), submit.

**Steps (API):**

```bash
python3 - <<'EOF'
import json, urllib.request
text = " ".join(
    f"At 2026-06-10T{9 + i // 60:02d}:{i % 60:02d}:00Z step {i} of the deploy sequence completed."
    for i in range(400)
)  # ~30k chars — well past CHUNK_MAX_CHARS
req = urllib.request.Request(
    "http://localhost:8090/api/jobs/ingest",
    json.dumps({"text": text, "title": "big-doc demo"}).encode(),
    {"Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())   # -> {"job_id": "..."}
EOF
curl -N localhost:8090/api/jobs/stream      # SSE: watch fraction climb 0.05 -> 1.0
curl -s localhost:8090/api/jobs/<job_id>    # final counts when status == "done"
```

**Expected:**
- Enqueue returns a `job_id` immediately (non-blocking).
- The SSE stream (and the queue dock in the UI, bottom-right) shows monotonically
  increasing progress with step labels ("Extracting events", "Inferring causal edges").
- `DELETE /api/jobs/{id}` cancels a queued/running job.
- Events from late chunks resolve relative times using the sliding context carried from
  earlier chunks.

---

## Wrap-up

```bash
curl -s -X POST localhost:8090/reset   # leave a clean instance behind
```

**What was demonstrated, in one paragraph:** raw text becomes timestamped events
(CT-1); events get cause→effect edges from temporal precedence + embedding association
+ one batched LLM judgment per event (CT-2); "why" questions return a time-ordered
root-cause chain with consequences and a cited narrative (CT-3, CT-5) while
keyword-similar noise is provably excluded (CT-3, CT-4) — in any domain, with no
hardcoded marker lists (CT-6); repeated observations reinforce instead of duplicate
(CT-7); causality can never run backward in time (CT-8); humans can assert what
inference missed (CT-9); and big documents ingest asynchronously with live progress
(CT-10).
