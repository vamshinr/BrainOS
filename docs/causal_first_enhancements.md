# Causal-First Enhancements — Proposed Code Additions (reference)

**Status:** PROPOSED, not yet implemented. Reference for picking up after the Vector Space
Day pitch. Companion to [`causal_first_positioning.md`](causal_first_positioning.md), which
explains the *why* (mapping Mnemosyne to Luo et al. 2501.14892 + Pavlyshyn).

**Guiding constraint:** the working demo must not regress. Each addition below is designed
to be **off by default** or **trigger only on an otherwise-empty result**, so the existing
`causal` retrieval path is byte-for-byte unchanged unless explicitly enabled.

---

## 1. Relation-type causal prior (`f(r)`) — effort S, risk LOW

**Why:** Luo's `Causality(r) = f(r)` ranks edges by relation *type* (CAUSE≈1.0,
ASSOCIATED_WITH≈0.4…). We currently store relation labels
(`caused/triggered/led_to/enabled/supersedes`) but weight them **uniformly** — only the
blended `confidence` matters. Adding a type prior lets us say "we implement the Luo
causality function" and nudges stronger relations up.

**Design (safe / reversible):**
- `mnemosyne/config.py` — add:
  - `relation_prior_weight: float` via `_f("RELATION_PRIOR_WEIGHT", 0.0)` — **default 0.0 = OFF**, so behavior is unchanged until enabled.
- New `RELATION_PRIORS` map (in `mnemosyne/pipeline/causal.py`), e.g.:
  `{"caused": 1.0, "triggered": 0.95, "led_to": 0.9, "enabled": 0.7, "supersedes": 0.5}`,
  default `0.6` for unknown relations.
- In `mnemosyne/pipeline/causal.py::infer_edges`, after computing the 3-signal blend
  `base = 0.3·temporal + 0.2·linguistic + 0.5·llm`, apply:
  `confidence = (1 - w)·base + w·RELATION_PRIORS.get(relation, 0.6)` where
  `w = settings.relation_prior_weight`. With `w = 0.0` this is exactly `base` (no change).
- **Tests:** with `w=0` confidence equals today's value (regression guard); with `w>0`,
  a `caused` edge outranks an `enabled` edge of equal base.

**Pitch line it unlocks:** "Each edge carries a learned 3-signal score *and* a relation-type
causal prior — strictly richer than the static `f(r)` lookup in Luo et al."

---

## 2. Auto causal→associative fallback — effort S, risk LOW

**Why:** Luo's pipeline tries the causal subgraph first and **falls back to the full KG** if
no causal path exists. Today our `causal` and `associative` modes are separate; a query with
no causal chain returns an empty chain (bad on stage). A graceful fallback removes demo risk.

**Design (triggers only on empty causal result):**
- `mnemosyne/pipeline/retrieval.py::retrieve_causal` — at the end, if `chain` is empty (no
  anchor found, or anchor has no edges ≥ threshold), call the existing
  `retrieve_associative(...)` and return its chunks under a clearly-labelled shape, e.g. add
  `"fallback": "associative"` to the response so the UI/`ask` route can show
  "No causal chain found — showing associative matches."
- `mnemosyne/api/schemas.py` / response: optional `fallback` field (None on the happy path).
- Frontend `src/app/ask/page.tsx` (or wherever causal results render): if `fallback ===
  "associative"`, show a small note. Happy path unchanged.
- **Tests:** a query with a known causal chain returns `fallback: None`; a query with no
  causal edges returns associative chunks + `fallback: "associative"`.

---

## 3. CoT-aligned multi-hop retrieval (the real differentiator) — effort M, risk MED → FAST-FOLLOW

**Why:** Luo's headline mechanism: split the LLM's chain-of-thought on "→" into steps, query
the causal graph **per step**, fuse, then re-synthesize. This is the one thing we don't do.
The ablation shows it adds the *last* ~1–2 points on top of causal filtering — valuable but
**not** the core — so it's a fast-follow, not a pre-pitch change.

**Design (separate, guarded mode — existing `causal` untouched):**
- Add a new retrieval mode `mode="causal_cot"` (alongside `causal` / `associative`) in
  `mnemosyne/service.py::retrieve` and `mnemosyne/pipeline/retrieval.py`.
- Steps:
  1. Prompt the LLM (Haiku) for a CoT for the query, segmented by "→" (extend
     `mnemosyne/llm/prompts.py`).
  2. For each consecutive segment pair, embed + anchor + traverse the causal graph for
     connecting paths (reuse existing anchor/traverse primitives).
  3. Fuse candidate paths; rank with a multi-factor score (see #4).
  4. Re-inject fused paths + CoT into the LLM for the final "why" synthesis
     (second-stage consistency pass, mirroring Luo §3.4).
- Keep `causal` as the default demo path; expose `causal_cot` behind a UI toggle.
- **Risk note:** CoT is stochastic (Luo's own caveat) — gate behind the toggle and consider
  self-consistency sampling later.

---

## 4. Multi-factor path scoring — effort S–M, risk LOW (pairs with #3)

**Why:** Luo ranks *paths*, not just edges:
`TotalScore = α·entity_overlap + β·semantic_overlap + γ·length_heuristic` (+ causal strength,
+ temporal validity in the article's variant). We currently traverse edges > threshold and
order by time, with no path *ranking*.

**Design:**
- Add a `score_path(path, query_embedding, settings)` helper in
  `mnemosyne/pipeline/retrieval.py` returning a blend of: mean edge confidence (causal
  strength), entity/tag overlap with the query, semantic similarity (cosine of path-summary
  vs query), a `1/(1+len)` length penalty, and a temporal-recency term using `occurred_at`.
- Use it to rank/trim candidate chains in `causal_cot` (#3); optionally to pick among
  multiple anchors in plain `causal`.
- Configurable weights in `config.py` (default to current behavior where applicable).

---

## 5. (Later / enterprise) Richer provenance & reification — effort M, risk LOW

**Why:** Pavlyshyn's enterprise angle: reified decisions (`causedBy`, `overridesPolicy`,
`authorizedBy`) over PROV-O. We have lighter provenance (`source_id`, edge
`evidence`/`method`). Only worth it for the enterprise "auditable decisions" pitch, not the
research demo.

**Design (sketch):** extend `CausalEdge` / event payloads with optional provenance fields
(actor, justification, supersedes, policy refs); surface them in `/event/{id}` and the graph
view. Defer until there's an enterprise design partner.

---

## Suggested order

| # | Item | Effort | Risk | When |
|---|---|---|---|---|
| 1 | Relation-type prior `f(r)` | S | Low | Pre-pitch (optional) |
| 2 | Causal→associative fallback | S | Low | Pre-pitch (optional) |
| 3 | CoT-aligned multi-hop mode | M | Med | Fast-follow |
| 4 | Multi-factor path scoring | S–M | Low | With #3 |
| 5 | Provenance / reification | M | Low | When enterprise partner exists |

Items 1–2 are independently shippable and reversible (off by default / fallback-only). 3–4
go together. 5 is demand-driven.
