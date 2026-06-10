# Causal Scorer Rework — Design

- **Date:** 2026-06-09
- **Status:** Implemented 2026-06-10, with deliberate deviations (see the note atop the
  implementation plan): the keyword/legacy path was deleted rather than preserved, and no
  `NotImplementedError` placeholders were added — per the directive to ship without stubs.
- **Component:** Mnemosyne backend — `mnemosyne/pipeline/causal.py` and the inference path
- **Context:** Core causal engine; Vector Space Day pitch ~Jun 11. Build the in-house
  "generalize + bound LLM cost" version now; stub interfaces for a local causal model and a
  learned calibrator to iterate on after testing.

## 1. Problem

Edge confidence is `0.3·temporal + 0.2·linguistic + 0.5·llm`. Two weaknesses:

1. **Generalization** — `linguistic_score` is a hardcoded English `CAUSAL_MARKERS` list +
   tag Jaccard. Brittle; doesn't transfer across domains/languages or capture semantic
   causal cues beyond the keyword list.
2. **Scalability** — `infer_edges` calls `llm.judge_causality` **per candidate pair**
   (every temporally-eligible pair, each ingest) → ≈ O(events × window-density) Haiku
   calls. That is the real cost/latency wall, more than the keyword matching.

## 2. Goals / Non-goals

**Goals**
- Replace the brittle linguistic heuristic with a **general** association signal
  (embedding cosine — already computed, no keyword list).
- **Bound** the LLM cost: pre-filter candidates to top-K, then **one batched judge call per
  ingested effect** (O(events), not O(pairs)).
- Make the scorer a **pluggable pipeline** so a local causal model and a learned calibrator
  drop in later via interfaces/config — stubbed now, off by default.
- Keep a **reversible** path to the legacy behavior (demo safety before the pitch).

**Non-goals**
- Implementing the local cross-encoder/NLI model or the learned calibrator (placeholders
  only this round).
- Changing retrieval/traversal, the temporal signal, or the storage schema.
- True causal inference — this stays *approximate* (temporal precedence + association + LLM).

## 3. Architecture — pluggable signal pipeline

`causal.py` is refactored from one hard-wired function into four swappable units behind
small Protocols, each with a **default in-house impl** and a **stub placeholder**:

| Unit | Interface | Default (build now) | Placeholder (stub, off) |
|---|---|---|---|
| Temporal | `temporal_score(...)` (unchanged fn) | `exp(−Δt/τ)` + precedence gate | — |
| Association | `AssociationSignal.score(cause, effect) -> float` | `EmbeddingCosine` | `CrossEncoderCausal` |
| Judge | `CausalJudge.judge(effect, causes) -> list[Judgment]` | `AnthropicBatchJudge` | `LocalCausalModel` |
| Calibrator | `Calibrator.confidence(t, a, llm) -> float` + `threshold()` | `StaticCalibrator` | `LearnedCalibrator` |

New files: `mnemosyne/pipeline/signals.py` (AssociationSignal impls + the candidate
selector), `mnemosyne/pipeline/calibration.py` (Calibrator impls). `causal.py` orchestrates.
The orchestration depends only on the interfaces.

## 4. Generalize — embedding association replaces markers+Jaccard

`EmbeddingCosine.score(cause, effect)` = cosine of the two event embeddings. Embeddings are
already L2-normalized (so cosine = dot product); near-free, general, cross-domain/language.
In practice, for the default embedding path the cosine is taken **directly from the
candidate-selection vector search** (§5) and passed through as the association score — no
extra embedding work. The `AssociationSignal` interface still exists as the seam where the
later `CrossEncoderCausal` recomputes a score from `(cause.text, effect.text)` instead of
reusing the cosine. The blend shape stays temporal/association/llm — only the middle term's
*source* changes. "Is this actually causal" remains with temporal precedence
(hard gate) + the LLM judge, and later graduates to `CrossEncoderCausal`.

## 5. Bound the LLM cost — pre-filter → top-K → one batched judge

Per ingested effect `e`:

1. **Candidate selection** (`select_candidates(e, graph, vector, settings)`):
   `vector.search(e.embedding, K_search)` returns `(cause_id, cosine, payload)` ranked by
   association; keep those whose `occurred_at ∈ [e.occurred_at − window, e.occurred_at]`
   (temporal precedence + lookback); take the **top-`CANDIDATE_TOP_K`** (default 5). The
   cosine is the association score; temporal is computed from `occurred_at`. Returns
   `[Candidate(cause: Event, temporal: float, association: float)]`.
2. **One batched judge** (`AnthropicBatchJudge.judge(e, [c.cause …])`): a single Haiku call
   returns `{relation, confidence, justification}` per candidate (new
   `judge_causality_batch` on the LLM client + a batched prompt). Falls back to neutral
   `llm=0` per candidate if the call/parse fails (edge still scored by temporal+association).
3. **Blend + emit**: `StaticCalibrator.confidence(temporal, association, llm)` (identical to
   today's weighted blend); build `CausalEdge` with relation from the judge; keep
   below-threshold edges (stored, excluded from default traversal — unchanged).

Result: **one LLM call per ingested event** instead of one per pair.

> Behavioral note: candidate generation moves from "every event in the temporal window"
> to "top-K by cosine within the window." This *can* change which edges form. It's gated by
> `CANDIDATE_TOP_K` and the `ASSOCIATION_SIGNAL`/`legacy` switch (§7) so it's tunable and
> reversible while testing.

## 6. Placeholders (real interfaces, zero behavior change until enabled)

- `CrossEncoderCausal(AssociationSignal)` and `LocalCausalModel(CausalJudge)`:
  same interfaces, bodies `raise NotImplementedError("placeholder — see spec")`. Selected
  only when the corresponding config opts in (default = in-house impls).
- `LearnedCalibrator(Calibrator)`: same interface; default stays `StaticCalibrator`.
- **Training-data hook:** `StaticCalibrator` (and the judge) optionally append
  `(temporal, association, llm, relation, final_confidence)` rows to a JSONL under the data
  dir when `SCORE_LOG=1`, so there's data to calibrate the learned version on later. Off by
  default.

## 7. Config + demo safety (all reversible)

New env knobs in `config.py::Settings`, defaulting to the new behavior:

- `ASSOCIATION_SIGNAL` = `embedding` (default) | `linguistic` (legacy markers+Jaccard) | `cross_encoder` (placeholder).
- `CANDIDATE_TOP_K` = `5`.
- `JUDGE_BATCH` = `true` (false → legacy per-pair judging).
- `JUDGE` = `anthropic` (default) | `local` (placeholder).
- `CALIBRATOR` = `static` (default) | `learned` (placeholder).
- `SCORE_LOG` = `false`.

Setting `ASSOCIATION_SIGNAL=linguistic` + `JUDGE_BATCH=false` reproduces today's behavior
exactly — the escape hatch if the new scoring shifts the demo unfavorably.

## 8. Error handling

- Batched judge call/parse failure → each candidate gets `llm=0.0`, `relation=caused`; the
  edge is still scored by temporal+association (degrades, never crashes ingest).
- Placeholder impls selected by config raise a clear `NotImplementedError` at construction
  (fail fast, not mid-ingest).
- `select_candidates` with an empty/cold vector store → no candidates → no edges (as today).

## 9. Testing

- `EmbeddingCosine`: related pair (parallel fake vectors) scores higher than an orthogonal pair.
- `select_candidates`: returns ≤ `CANDIDATE_TOP_K`, all within the temporal window, ranked by
  cosine (fake graph + fake vector store; no Neo4j/Qdrant needed).
- `AnthropicBatchJudge`: a fake LLM records **one** call for K candidates and the result is
  parsed per-candidate; parse-failure path yields neutral judgments.
- `StaticCalibrator.confidence(...)` **equals** today's `blend(...)` on the same inputs
  (regression guard — proves the refactor is behavior-preserving).
- Placeholders raise `NotImplementedError` when selected; defaults selected otherwise.
- Existing causal/retrieval/model tests still pass; the legacy switch reproduces prior edges
  on a fixed fixture.

## 10. Files

**New:** `mnemosyne/pipeline/signals.py` (AssociationSignal impls + `select_candidates`),
`mnemosyne/pipeline/calibration.py` (Calibrator impls), tests
`tests/test_signals.py`, `tests/test_calibration.py`.
**Modified:** `mnemosyne/pipeline/causal.py` (orchestrate the pipeline; keep `temporal_score`;
move legacy `linguistic_score` behind the `linguistic` option), `interfaces.py`
(`LLMClient.judge_causality_batch`), `llm/anthropic_client.py` + `llm/prompts.py` (batched
judge), `service.py` (candidate-gen via vector+temporal), `config.py` (the §7 knobs).

## 11. Future (after testing option 2)

- Implement `CrossEncoderCausal` (local NLI/cross-encoder, batched, offline) — the true
  general causal-direction signal; ties to the vLLM/MI300X infra story.
- Implement `LearnedCalibrator` (logistic over the logged `(signals → outcome)` rows) +
  a principled, calibrated threshold — which then makes a materialized `CAUSES_STRONG`
  subgraph safe (the Q2 latency win).
