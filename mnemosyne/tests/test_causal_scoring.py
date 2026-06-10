"""Stage B scoring: candidate selection, signal blending, and edge inference.

Pure unit tests with fakes — no Neo4j/Qdrant/LLM required. The key invariant under
test: edge inference makes exactly ONE batched judge call per ingested effect,
regardless of how many candidates were selected.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

from mnemosyne.config import Settings
from mnemosyne.models import METHOD_BLEND, METHOD_NO_LLM, Event
from mnemosyne.pipeline.causal import blend, infer_edges, select_candidates

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)
_S = Settings()


def _ev(id_: str, minutes_before: float) -> Event:
    return Event(
        id=id_,
        summary=f"event {id_}",
        detail="",
        occurred_at=NOW - timedelta(minutes=minutes_before),
        learned_at=NOW,
        tags=[],
        embedding=[1.0, 0.0],
    )


class FakeGraph:
    def __init__(self, events):
        self._by_id = {e.id: e for e in events}

    def get_event(self, event_id):
        return self._by_id.get(event_id)


class FakeVector:
    """Returns canned (id, cosine, payload) hits in the given order."""

    def __init__(self, hits):
        self._hits = hits

    def search(self, vector, k):
        return self._hits[:k]


class FakeJudge:
    def __init__(self, relation="caused", confidence=0.9, fail=False):
        self.calls = 0
        self._relation = relation
        self._confidence = confidence
        self._fail = fail

    def judge_causality_batch(self, effect, causes):
        self.calls += 1  # must be ONE call for all candidates
        if self._fail:
            raise RuntimeError("judge unavailable")
        return [
            {
                "cause_id": c.id,
                "relation": self._relation,
                "confidence": self._confidence,
                "justification": "fake",
            }
            for c in causes
        ]


# --------------------------------------------------------------------- blend


def test_blend_weights():
    # default weights 0.3 (temporal) / 0.2 (association) / 0.5 (llm)
    assert abs(blend(1.0, 1.0, 1.0, _S) - 1.0) < 1e-9
    assert abs(blend(1.0, 0.0, 0.0, _S) - _S.weight_temporal) < 1e-9
    assert abs(blend(0.0, 1.0, 0.0, _S) - _S.weight_association) < 1e-9
    assert abs(blend(0.0, 0.0, 1.0, _S) - _S.weight_llm) < 1e-9


# --------------------------------------------------- candidate selection


def test_select_candidates_filters_by_time_and_caps_at_top_k():
    effect = _ev("E", 0)
    causes = [_ev("c1", 10), _ev("c2", 5), _ev("c3", 1)]
    future = _ev("future", -5)  # occurs AFTER the effect -> must be pruned
    graph = FakeGraph(causes + [future, effect])
    vector = FakeVector(
        [
            ("E", 1.0, {}),
            ("future", 0.99, {}),
            ("c1", 0.9, {}),
            ("c2", 0.8, {}),
            ("c3", 0.7, {}),
        ]
    )
    s = dataclasses.replace(_S, candidate_top_k=2)
    cands = select_candidates(effect, graph, vector, s)

    ids = [c.cause.id for c in cands]
    assert "E" not in ids and "future" not in ids  # self + future pruned
    assert len(cands) == 2  # capped at top_k
    assert all(c.temporal > 0 and 0.0 <= c.association <= 1.0 for c in cands)


def test_select_candidates_prunes_outside_lookback_window():
    effect = _ev("E", 0)
    ancient = _ev("ancient", _S.temporal_max_window_s / 60 + 10)
    graph = FakeGraph([effect, ancient])
    vector = FakeVector([("ancient", 0.95, {})])
    assert select_candidates(effect, graph, vector, _S) == []


def test_select_candidates_empty_without_embedding():
    effect = _ev("E", 0).model_copy(update={"embedding": None})
    assert select_candidates(effect, FakeGraph([]), FakeVector([]), _S) == []


def test_select_candidates_skips_ids_missing_from_graph():
    effect = _ev("E", 0)
    graph = FakeGraph([effect])  # vector store knows "ghost", graph does not
    vector = FakeVector([("ghost", 0.9, {})])
    assert select_candidates(effect, graph, vector, _S) == []


# ----------------------------------------------------------- edge inference


def _setup():
    effect = _ev("E", 0)
    c1, c2 = _ev("c1", 10), _ev("c2", 5)
    graph = FakeGraph([effect, c1, c2])
    vector = FakeVector([("E", 1.0, {}), ("c1", 0.8, {}), ("c2", 0.7, {})])
    return effect, graph, vector


def test_infer_edges_one_batched_call_and_blended_edges():
    effect, graph, vector = _setup()
    judge = FakeJudge()
    edges = infer_edges(effect, graph=graph, vector=vector, settings=_S, llm=judge)

    assert judge.calls == 1  # bounded: ONE call, not per-pair
    assert {e.cause_id for e in edges} == {"c1", "c2"}
    assert all(e.effect_id == "E" for e in edges)
    assert all(e.method == METHOD_BLEND for e in edges)
    # llm=0.9 dominates the blend; these clear the default 0.55 threshold
    assert all(e.confidence > _S.confidence_threshold for e in edges)


def test_infer_edges_without_llm_renormalizes_and_still_builds_edges():
    effect, graph, vector = _setup()
    edges = infer_edges(effect, graph=graph, vector=vector, settings=_S, llm=None)
    assert {e.cause_id for e in edges} == {"c1", "c2"}
    assert all(e.method == METHOD_NO_LLM for e in edges)
    # no-LLM: (wt*t + wa*assoc)/(wt+wa) -> in (0, 1]
    assert all(0.0 < e.confidence <= 1.0 for e in edges)


def test_infer_edges_degrades_when_judge_fails():
    effect, graph, vector = _setup()
    judge = FakeJudge(fail=True)
    edges = infer_edges(effect, graph=graph, vector=vector, settings=_S, llm=judge)
    assert judge.calls == 1
    # judge failure must not crash ingest: edges still form from temporal+association
    assert {e.cause_id for e in edges} == {"c1", "c2"}
    assert all(e.method == METHOD_NO_LLM for e in edges)


def test_infer_edges_none_relation_scores_below_threshold():
    effect, graph, vector = _setup()
    judge = FakeJudge(relation="none", confidence=0.05)
    edges = infer_edges(effect, graph=graph, vector=vector, settings=_S, llm=judge)
    # "none" verdicts are kept (stored) but must land below the traversal threshold
    assert len(edges) == 2
    assert all(e.confidence < _S.confidence_threshold for e in edges)


def test_infer_edges_empty_when_no_candidates():
    effect = _ev("E", 0)
    edges = infer_edges(
        effect,
        graph=FakeGraph([effect]),
        vector=FakeVector([("E", 1.0, {})]),
        settings=_S,
        llm=None,
    )
    assert edges == []
