"""Stage B — causal edge inference (the hard part).

Three-signal scoring. We deliberately do NOT rely on the LLM alone, nor on heuristics
alone — we combine:

  1. Temporal precedence + proximity. A cause must occur before the effect; the score
     decays with the time gap and prunes the candidate set cheaply.
  2. Linguistic / co-occurrence cues. Explicit causal markers in the text plus shared
     entities/tags raise the prior.
  3. LLM causal judgment (Haiku) for the surviving pairs.

final confidence = 0.3*temporal + 0.2*linguistic + 0.5*llm (then tune).

Honest note: this is *approximate* causality (temporal precedence + association + an
LLM judgment), not true causal inference. That is the accepted practical tradeoff.
"""

from __future__ import annotations

import math
from typing import Optional

from ..config import Settings
from ..interfaces import LLMClient
from ..models import (
    CAUSAL_RELATIONS,
    METHOD_BLEND,
    RELATION_CAUSED,
    CausalEdge,
    Event,
    build_causal_edge,
)

# Explicit causal markers we look for in the effect's text.
CAUSAL_MARKERS = [
    "because",
    "due to",
    "caused",
    "led to",
    "leads to",
    "triggered",
    "as a result",
    "resulted in",
    "results in",
    "consequently",
    "thereby",
    "which caused",
    "so that",
    "owing to",
    "in response to",
    "following the",
    "after the",
]


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = {t.lower() for t in a}, {t.lower() for t in b}
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


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


def linguistic_score(cause: Event, effect: Event) -> tuple[float, list[str]]:
    """Signal 2. Marker presence in the effect text + entity/tag overlap. Returns
    (score in 0..1, matched markers)."""
    text = f"{effect.summary} {effect.detail}".lower()
    hits = [m for m in CAUSAL_MARKERS if m in text]
    marker = 0.5 if hits else 0.0
    overlap = _jaccard(cause.tags, effect.tags)
    score = marker + 0.5 * min(1.0, overlap * 2.0)
    return min(1.0, score), hits


def blend(temporal: float, linguistic: float, llm_conf: float, settings: Settings) -> float:
    return (
        settings.weight_temporal * temporal
        + settings.weight_linguistic * linguistic
        + settings.weight_llm * llm_conf
    )


def score_pair(
    cause: Event,
    effect: Event,
    *,
    settings: Settings,
    llm: Optional[LLMClient] = None,
) -> Optional[CausalEdge]:
    """Score a single (cause, effect) candidate with all three signals and return a
    CausalEdge, or None if the pair is pruned at the temporal stage.

    When ``llm`` is None (deterministic unit tests) the LLM signal is dropped and the
    remaining two signals are renormalized.
    """
    t = temporal_score(
        cause, effect, tau_s=settings.temporal_tau_s, max_window_s=settings.temporal_max_window_s
    )
    if t is None:
        return None

    ling, markers = linguistic_score(cause, effect)

    if llm is not None:
        judgment = llm.judge_causality(cause, effect)
        relation = judgment.get("relation", RELATION_CAUSED)
        llm_conf = float(judgment.get("confidence", 0.0) or 0.0)
        justification = judgment.get("justification", "")
        if relation not in CAUSAL_RELATIONS:  # "none" or unknown
            relation = RELATION_CAUSED
            # keep llm_conf (low) — the blend will likely fall below threshold
        confidence = blend(t, ling, llm_conf, settings)
        method = METHOD_BLEND
        evidence = (
            f"temporal={t:.2f}; linguistic={ling:.2f} markers={markers}; "
            f"llm={llm_conf:.2f}: {justification}"
        )
    else:
        relation = RELATION_CAUSED
        denom = settings.weight_temporal + settings.weight_linguistic or 1.0
        confidence = (settings.weight_temporal * t + settings.weight_linguistic * ling) / denom
        method = "temporal+linguistic"
        evidence = f"temporal={t:.2f}; linguistic={ling:.2f} markers={markers} (no-LLM)"

    return build_causal_edge(
        cause,
        effect,
        relation=relation,
        confidence=round(confidence, 4),
        evidence=evidence,
        method=method,
    )


def infer_edges(
    effect: Event,
    candidates: list[Event],
    *,
    settings: Settings,
    llm: Optional[LLMClient] = None,
) -> list[CausalEdge]:
    """Score every candidate cause for ``effect`` and return the surviving edges.
    All edges that survive temporal pruning are returned (including below-threshold
    ones — they are stored but excluded from default traversal)."""
    edges: list[CausalEdge] = []
    for cause in candidates:
        if cause.id == effect.id:
            continue
        edge = score_pair(cause, effect, settings=settings, llm=llm)
        if edge is not None:
            edges.append(edge)
    return edges
