# Causal-First Memory — How Mnemosyne Maps to Luo et al. & Pavlyshyn

**Purpose:** Positioning note for the Vector Space Day SF pitch (Qdrant, ~Jun 11 2026).
Shows that two independent sources argue for "causal-first memory," that Mnemosyne
already *is* that layer, where it is ahead, and the honest gaps + roadmap.

**Date:** 2026-06-07

## The two sources

1. **Luo, Zhang, Li — *Causal Graphs Meet Thoughts: Enhancing Complex Reasoning in
   Graph-Augmented LLMs*** (arXiv **2501.14892v2**, Mar 2025). Peer-style empirical paper.
2. **Volodymyr Pavlyshyn — *Causal Graphs as the Missing Layer*** (Substack synthesis).
   Popularization that **borrows its headline numbers directly from Luo et al.**

Both make the same argument: vector RAG and ordinary knowledge graphs **conflate
correlation with causation**; the "missing layer" is a mechanism that **prioritizes
cause→effect edges over correlational ones**, with temporal + provenance metadata.

## What Luo et al. proves, and how

**Claim:** "Causal-First Graph-RAG" — filter a large KG to causal edges, then retrieve
*in lockstep with the LLM's chain-of-thought (CoT)* — beats both a vanilla LLM and
traditional Graph-RAG on knowledge-intensive medical QA.

**Method (3 stages):**
1. **Causal filtering** — keep edges where `Causality(r) = f(r) ≥ θ` (a relation-type
   lookup: CAUSE≈1.0, ASSOCIATED_WITH≈0.4, CO_OCCURS≈0.2); update strengths via causal
   mining (PC algorithm).
2. **CoT-driven retrieval** — LLM emits a CoT split on "→" into segments `s₁→s₂→s₃`; for
   each consecutive pair, run entity recognition and query the **causal subgraph** for
   connecting paths, **falling back to the full KG** if none exist.
3. **Multi-stage path processing** — merge duplicate paths; score
   `PathScore = Σ strength / L`, then `TotalScore = α·CUI_overlap + β·semantic_overlap +
   γ·length_heuristic`; keep top-k; **re-inject paths + CoT into the LLM** for a
   consistency check ("enhanced" answer).

**Setup:** MedMCQA + MedQA (medical multiple-choice); SemMedDB KG; GPT-4o / GPT-4 / 4o-mini;
metrics Precision/Recall/F1.

**Results (Table 1, MedMCQA precision):**

| System | GPT-4o | GPT-4 | GPT-4o-mini |
|---|---|---|---|
| Direct LLM | 85.52 | 84.15 | 72.13 |
| Traditional Graph-RAG | 86.89 | 82.51 | 75.41 |
| **CGMT (theirs)** | **92.90** | 87.98 | 82.51 |

Up to **+10pp** (4o-mini: 72.13→82.51), +7.4pp (4o: 85.52→92.90). Consistent across models.

**Ablation (Table 2) — the most important detail for us:** "KG-only" = causal filtering
**with no CoT and no enhancement** already reaches **91.80** of the 92.90 for GPT-4o.
**⇒ Causal filtering is the dominant lever; CoT-alignment + re-injection add the last ~1–2pts.**

**Honest caveats (for Q&A):**
- **Selection bias** — "only items mapping into the causal subgraph are retained for testing."
- Medical-only, multiple-choice-only.
- **CoT is stochastic** — same question can retrieve differently run-to-run.
- Causal subgraphs have coverage gaps → correlational fallback is needed.

## Mnemosyne vs. the Luo/Pavlyshyn approach

### Where Mnemosyne already *is* the thing they argue for

| Their claim / mechanism | Mnemosyne today |
|---|---|
| Causality as a first-class citizen | The entire model is event→event causal edges, not co-occurrence. |
| Filter edges by `f(r) ≥ θ` | Filter by `CONFIDENCE_THRESHOLD = 0.55`, with a **richer per-edge score than a relation-type lookup**: `confidence = 0.3·temporal + 0.2·linguistic + 0.5·LLM`. Instance-level vs. their type-level table — **we are more sophisticated here.** |
| Bi-temporal (`t_valid` vs `t_transaction`) | Already have `occurred_at` (valid) + `learned_at` (transaction) per event, **plus a hard temporal-precedence invariant** (`cause.occurred_at ≤ effect.occurred_at`) neither source enforces. |
| Retrieve causal pathways (root-cause back, consequences forward) | Exactly our causal traversal. |
| "Filtering removes correlational noise" | `/retrieve` returns **`excluded_distractors`** — the semantically-similar events deliberately left off the causal path. **A live, visual proof of the paper's central claim.** |
| "Required to build one: causal discovery / LLM scoring" | They **assume** a pre-built KG (SemMedDB). We **construct** the causal graph from raw text via LLM extraction + 3-signal inference. **We solve the harder upstream problem.** |

### Honest gaps

| Their mechanism | Mnemosyne | Gap |
|---|---|---|
| **CoT-aligned stepwise retrieval** | We retrieve once: anchor → traverse → synthesize | **Biggest** (their #2 contribution) |
| Multi-factor path scoring | Traverse edges > threshold + time-order; no path *ranking* | Medium |
| Relation-type weighting `f(r)` | Relations stored but weighted **uniformly** in traversal | Small (easy win) |
| Auto causal→correlational fallback | `causal` / `associative` are separate modes, not an auto-fallback | Small |
| Second-stage LLM consistency re-injection | Synthesize once, no verification pass | Small–medium |
| Full PROV-O reification (who/why/authorizedBy) | Lighter provenance (`source_id`, edge `evidence`/`method`) | Medium (enterprise angle) |

## Pitch narrative (talking points)

- "A peer-reviewed result (Luo et al., 2025) **and** an independent practitioner synthesis
  (Pavlyshyn) both converge on **causal-first memory as the missing layer.**"
- "Mnemosyne **is** that layer — and goes further: it **builds** the causal graph from raw
  text (they assume one exists), scores each edge with a **3-signal blend** (they use a
  static type lookup), enforces **temporal precedence** as an invariant, and **shows you the
  correlational distractors it rejected.**"
- The `excluded_distractors` view on screen is the single most pitch-able artifact in this
  space — it *demonstrates* the thesis the paper only *measures*.
- Ties to our mnemonic-engineering manifesto: the article's 4-layer stack (semantic
  spacetime → context graph → causal KG → synthetic reasoning) is **independent validation**
  of our layered CCS.

## Recommended roadmap (1-week-to-pitch)

Don't rebuild retrieval before the demo. The ablation says causal filtering is the dominant
lever and we already do it — better than they do. Priorities by leverage × risk:

1. **Narrative / positioning** (free) — use this doc for the deck.
2. **Relation-type causal prior** (S) — fold an `f(r)`-style weight into edge confidence /
   traversal so we can say "we implement the Luo causality function."
3. **Auto causal→associative fallback** (S) — when a query yields no causal chain, fall back
   to associative neighbors; removes empty-result demo risk.
4. **CoT-aligned multi-hop retrieval** (M) — the real differentiator; **fast-follow**, built
   as a *separate, guarded* retrieval mode so the existing demo path can't break.

## References

- Luo, Zhang, Li (2025), arXiv:2501.14892v2 — local copy: `2501.14892v2.pdf` (repo root).
- Pavlyshyn, *Causal Graphs as the Missing Layer* —
  https://volodymyrpavlyshyn.substack.com/p/causal-graphs-as-the-missing-layer
- Related internal docs: `merged_product_strategy.md`, `mnemonic_engineering_manifesto.md`,
  `vector_space_day_research.md`.
