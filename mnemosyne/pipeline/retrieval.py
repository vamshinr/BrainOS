"""Retrieval — the payoff.

Associative mode (baseline): embed query -> Qdrant top-k -> return chunks. No ordering.
Exists only to demonstrate the difference.

Causal mode (the real thing):
  1. Anchor: embed the query, find the best-matching event (the "effect" asked about).
  2. Traverse backward over cause edges (above the confidence threshold) to root cause(s).
  3. Traverse forward (optional) over effect edges to capture resolution/consequences.
  4. Order by occurred_at, return the chain with edge relations + confidences.
  5. Synthesize: hand the ordered chain to the LLM for the "why" narrative.

``excluded_distractors`` — semantically-similar events that are NOT on any causal path —
is the demonstrable proof that causal traversal ignores keyword-similar noise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Settings
from ..interfaces import Embedder, GraphStore, LLMClient, VectorStore
from .consolidation import salience


def _event_to_dict(ev, now: datetime, settings: Settings) -> dict[str, Any]:
    return {
        "id": ev.id,
        "summary": ev.summary,
        "detail": ev.detail,
        "occurred_at": ev.occurred_at.isoformat(),
        "learned_at": ev.learned_at.isoformat(),
        "tags": ev.tags,
        "source_id": ev.source_id,
        "reinforcement_count": ev.reinforcement_count,
        "salience": round(salience(ev, now, settings.salience_half_life_s), 4),
    }


def retrieve_associative(
    query: str,
    k: int,
    *,
    embedder: Embedder,
    vector: VectorStore,
    graph: GraphStore,
    settings: Settings,
) -> dict[str, Any]:
    qv = embedder.embed_one(query)
    now = datetime.now(timezone.utc)
    chunks = []
    for eid, score, payload in vector.search(qv, k):
        ev = graph.get_event(eid)
        chunks.append(
            {
                "id": eid,
                "score": round(score, 4),
                "event": _event_to_dict(ev, now, settings) if ev else None,
                "payload": payload if ev is None else None,
            }
        )
    return {"mode": "associative", "query": query, "chunks": chunks}


def _collect(graph: GraphStore, start_id: str, threshold: float, max_hops: int, backward: bool) -> set[str]:
    visited: set[str] = set()
    frontier = [start_id]
    hops = 0
    while frontier and hops < max_hops:
        nxt: list[str] = []
        for nid in frontier:
            edges = (
                graph.incoming_edges(nid, threshold) if backward else graph.outgoing_edges(nid, threshold)
            )
            for e in edges:
                other = e.cause_id if backward else e.effect_id
                if other not in visited and other != start_id:
                    visited.add(other)
                    nxt.append(other)
        frontier = nxt
        hops += 1
    return visited


def _fallback_narrative(query: str, entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "No causal chain found for this query."
    if len(entries) == 1:
        return f"Cause not yet established; anchor event [{entries[0]['event']['id']}]."
    steps = []
    for e in entries:
        ev = e["event"]
        rel = e.get("incoming_relation")
        prefix = "root cause" if not rel else rel
        steps.append(f"[{ev['id']}] {ev['occurred_at']} ({prefix}): {ev['summary']}")
    return "Causal chain (root -> outcome): " + "  ->  ".join(steps)


def retrieve_causal(
    query: str,
    k: int,
    *,
    embedder: Embedder,
    vector: VectorStore,
    graph: GraphStore,
    settings: Settings,
    llm: Optional[LLMClient] = None,
) -> dict[str, Any]:
    qv = embedder.embed_one(query)
    n = max(k, settings.anchor_top_k)
    hits = vector.search(qv, n)
    if not hits:
        return {
            "mode": "causal",
            "query": query,
            "anchor_event_id": None,
            "chain": [],
            "answer": "No matching events.",
            "excluded_distractors": [],
        }

    threshold = settings.confidence_threshold
    # Anchor = the highest-similarity hit that actually participates in the causal graph,
    # so we don't anchor on an isolated semantic distractor.
    anchor_id = hits[0][0]
    for eid, _score, _payload in hits:
        if graph.edges_for_event(eid):
            anchor_id = eid
            break

    ancestors = _collect(graph, anchor_id, threshold, settings.max_hops, backward=True)
    descendants = (
        _collect(graph, anchor_id, threshold, settings.max_hops, backward=False)
        if settings.forward_traversal
        else set()
    )
    chain_ids = {anchor_id} | ancestors | descendants

    now = datetime.now(timezone.utc)
    entries: list[dict[str, Any]] = []
    for cid in chain_ids:
        ev = graph.get_event(cid)
        if ev is None:
            continue
        in_chain = [e for e in graph.incoming_edges(cid, threshold) if e.cause_id in chain_ids]
        best = max(in_chain, key=lambda e: e.confidence) if in_chain else None
        entries.append(
            {
                "event": _event_to_dict(ev, now, settings),
                "incoming_relation": best.relation if best else None,
                "confidence": round(best.confidence, 4) if best else None,
                "_sort": (ev.occurred_at, -salience(ev, now, settings.salience_half_life_s)),
            }
        )
    entries.sort(key=lambda x: x.pop("_sort"))

    distractors = [eid for eid, _s, _p in hits if eid not in chain_ids]

    # The causal chain is the valuable result; the narrative is a nice-to-have. If the
    # LLM is unavailable (no key, auth error, rate limit), degrade to the deterministic
    # narrative instead of failing the whole retrieval.
    answer = _fallback_narrative(query, entries)
    if llm is not None:
        try:
            answer = llm.synthesize(query, entries)
        except Exception:  # noqa: BLE001
            answer = _fallback_narrative(query, entries)
    return {
        "mode": "causal",
        "query": query,
        "anchor_event_id": anchor_id,
        "chain": entries,
        "answer": answer,
        "excluded_distractors": distractors,
    }
