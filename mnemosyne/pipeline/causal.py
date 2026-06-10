"""Stage B — causal edge inference.

Three-signal scoring. We deliberately do NOT rely on the LLM alone, nor on heuristics
alone — we combine:

  1. Temporal precedence + proximity. A cause must occur before the effect; the score
     decays with the time gap and prunes the candidate set cheaply.
  2. Semantic association. The cosine between the two events' embeddings, taken
     directly from the candidate vector search — general across domains and languages,
     no keyword lists.
  3. LLM causal judgment (Haiku), batched: the top-K candidates for an effect are
     judged in ONE call, so the LLM cost is O(events), not O(pairs).

final confidence = weight_temporal*temporal + weight_association*association + weight_llm*llm.

Honest note: this is *approximate* causality (temporal precedence + association + an
LLM judgment), not true causal inference. That is the accepted practical tradeoff.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

from ..config import Settings
from ..interfaces import GraphStore, LLMClient, VectorStore
from ..models import (
    CAUSAL_RELATIONS,
    METHOD_BLEND,
    METHOD_NO_LLM,
    RELATION_CAUSED,
    CausalEdge,
    Event,
    build_causal_edge,
)


def temporal_score(
    cause: Event, effect: Event, *, tau_s: float, max_window_s: float
) -> Optional[float]:
    """Signal 1. Returns None when the candidate should be pruned (cause does not
    precede effect, or the gap exceeds the lookback window). Otherwise a 0..1 score
    that decays exponentially with the time gap (half-life ~tau_s)."""
    delta = (effect.occurred_at - cause.occurred_at).total_seconds()
    if delta < 0:
        return None  # cause after effect — invalid
    if delta > max_window_s:
        return None  # too far apart — prune cheaply
    return math.exp(-delta / tau_s)


def blend(temporal: float, association: float, llm_conf: float, settings: Settings) -> float:
    return (
        settings.weight_temporal * temporal
        + settings.weight_association * association
        + settings.weight_llm * llm_conf
    )


@dataclass
class Candidate:
    """A temporally-eligible prior event, with its two cheap signals precomputed."""

    cause: Event
    temporal: float
    association: float  # embedding cosine from the candidate vector search


def select_candidates(
    effect: Event, graph: GraphStore, vector: VectorStore, settings: Settings
) -> list[Candidate]:
    """The top-K prior events most associated with ``effect``.

    The vector search supplies both the candidate set and the association signal
    (cosine); the temporal gate enforces precedence and the lookback window. Ranked
    by temporal*association so the judge sees the strongest joint candidates."""
    if not effect.embedding:
        return []
    k_search = max(settings.candidate_top_k * 4, 20)
    candidates: list[Candidate] = []
    for cause_id, cosine, _payload in vector.search(effect.embedding, k_search):
        if cause_id == effect.id:
            continue
        cause = graph.get_event(cause_id)
        if cause is None:
            continue
        t = temporal_score(
            cause,
            effect,
            tau_s=settings.temporal_tau_s,
            max_window_s=settings.temporal_max_window_s,
        )
        if t is None:  # cause after effect, or outside the lookback window
            continue
        # Clamp: cosine similarity of normalized embeddings can be slightly negative.
        association = min(1.0, max(0.0, float(cosine)))
        candidates.append(Candidate(cause=cause, temporal=t, association=association))
    candidates.sort(key=lambda c: c.temporal * c.association, reverse=True)
    return candidates[: settings.candidate_top_k]


def infer_edges(
    effect: Event,
    *,
    graph: GraphStore,
    vector: VectorStore,
    settings: Settings,
    llm: Optional[LLMClient] = None,
) -> list[CausalEdge]:
    """Infer causal edges into ``effect``: select the top-K associated prior events,
    judge them in ONE batched LLM call, and blend the three signals into confidence.

    All selected candidates yield an edge (including below-threshold ones — they are
    stored but excluded from default traversal). A judge failure degrades to the
    temporal+association blend; it never crashes ingest. When ``llm`` is None
    (deterministic tests) the remaining two signals are renormalized."""
    candidates = select_candidates(effect, graph, vector, settings)
    if not candidates:
        return []

    judgments: dict[str, dict[str, Any]] = {}
    if llm is not None:
        try:
            for j in llm.judge_causality_batch(effect, [c.cause for c in candidates]):
                judgments[str(j.get("cause_id", ""))] = j
        except Exception:  # noqa: BLE001 — degrade, never crash ingest
            judgments = {}

    edges: list[CausalEdge] = []
    for c in candidates:
        judgment = judgments.get(c.cause.id)
        if judgment is not None:
            relation = judgment.get("relation", RELATION_CAUSED)
            llm_conf = float(judgment.get("confidence", 0.0) or 0.0)
            if relation not in CAUSAL_RELATIONS:  # "none" or unknown
                relation = RELATION_CAUSED
                # keep llm_conf (low) — the blend will likely fall below threshold
            confidence = blend(c.temporal, c.association, llm_conf, settings)
            method = METHOD_BLEND
            evidence = (
                f"temporal={c.temporal:.2f}; association={c.association:.2f}; "
                f"llm={llm_conf:.2f}: {judgment.get('justification', '')}"
            )
        else:
            relation = RELATION_CAUSED
            denom = (settings.weight_temporal + settings.weight_association) or 1.0
            confidence = (
                settings.weight_temporal * c.temporal
                + settings.weight_association * c.association
            ) / denom
            method = METHOD_NO_LLM
            evidence = f"temporal={c.temporal:.2f}; association={c.association:.2f} (no-LLM)"

        edges.append(
            build_causal_edge(
                c.cause,
                effect,
                relation=relation,
                confidence=round(confidence, 4),
                evidence=evidence,
                method=method,
            )
        )
    return edges
