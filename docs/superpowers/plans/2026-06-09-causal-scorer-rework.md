# Causal Scorer Rework Implementation Plan

> **OUTCOME (2026-06-10): Implemented, with deliberate deviations.** The architecture
> shipped as specced — embedding-cosine association from the candidate vector search,
> top-K candidate selection, ONE batched judge call per ingested event, weighted blend —
> but per an explicit product directive ("no stubs, no patches, no keyword searches"):
> - The legacy keyword path (`CAUSAL_MARKERS`, `linguistic_score`, per-pair `score_pair`/
>   `judge_causality`, the `SCORER=legacy` switch) was **deleted**, not preserved.
> - No placeholder classes (`CrossEncoderCausal`, `LocalCausalModel`, `LearnedCalibrator`)
>   were added; the config knobs that existed only to select them were dropped too.
> - Everything lives in a rewritten `mnemosyne/pipeline/causal.py` (no separate
>   signals/calibration/scoring modules — without the plugin seams there was nothing to
>   separate). `weight_linguistic` was renamed `weight_association` (`WEIGHT_ASSOCIATION`).
> - `GraphStore.candidate_causes` became dead and was removed from the interface and the
>   Neo4j store. Tests: `test_causal_scoring.py` + `test_batch_judge.py` replace
>   `test_causal_blend.py` + `test_linguistic_signal.py`.
> Verified: 47 passed (incl. the live Anthropic end-to-end test), 1 destructive skip.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the brittle keyword "linguistic" signal with embedding-based association and bound the LLM cost to one batched judge call per ingested event, behind a pluggable signal pipeline with stubbed placeholders for a local causal model and a learned calibrator.

**Architecture:** Keep the existing legacy functions in `causal.py` intact (they power a reversible `SCORER=legacy` path and existing tests). Add three focused modules — `signals.py` (association + candidate selection), `calibration.py` (blend/threshold), `scoring.py` (`infer_edges_hybrid` orchestration) — plus a batched judge on the LLM client. `service.py` picks hybrid (default) or legacy by config.

**Tech Stack:** Python 3.13 · sentence-transformers (MiniLM, L2-normalized) · Qdrant (cosine) · Neo4j · Anthropic Haiku · pytest.

**Spec:** `docs/superpowers/specs/2026-06-09-causal-scorer-rework-design.md`

**Conventions:** run tests with `mnemosyne/.venv/bin/python -m pytest` from the repo root. The new unit tests use fakes and need **no** Neo4j/Qdrant/LLM. Commit after each task. Branch `Release_V2`.

---

## File Structure

- **Create** `mnemosyne/pipeline/signals.py` — `Candidate`, `AssociationSignal` protocol, `EmbeddingCosine`, `CrossEncoderCausal` (stub), `select_candidates`, `make_association`.
- **Create** `mnemosyne/pipeline/calibration.py` — `Calibrator` protocol, `StaticCalibrator`, `LearnedCalibrator` (stub), `make_calibrator`.
- **Create** `mnemosyne/pipeline/scoring.py` — `infer_edges_hybrid` orchestration + `LocalCausalModel` (stub).
- **Modify** `mnemosyne/config.py` — scorer knobs.
- **Modify** `mnemosyne/interfaces.py` — `LLMClient.judge_causality_batch`.
- **Modify** `mnemosyne/llm/prompts.py` — batched judge prompt + tool.
- **Modify** `mnemosyne/llm/anthropic_client.py` — `judge_causality_batch` + `_parse_batch`.
- **Modify** `mnemosyne/service.py` — branch hybrid/legacy.
- **Keep unchanged** `mnemosyne/pipeline/causal.py` (legacy path + existing tests).
- **Tests:** `tests/test_calibration.py`, `tests/test_signals.py`, `tests/test_scoring.py`, `tests/test_batch_judge.py`.

---

## Task 1: Config knobs

**Files:** Modify `mnemosyne/config.py`, `.env.example`

- [ ] **Step 1: Add settings**

In `mnemosyne/config.py`, add inside `Settings` immediately after the `job_recent_limit` line (before `# --- Causal engine tuning ---`):

```python
    # --- Causal scorer rework (SCORER=legacy reproduces the pre-rework behavior) ---
    scorer: str = field(default_factory=lambda: _s("SCORER", "hybrid"))  # hybrid | legacy
    candidate_top_k: int = field(default_factory=lambda: _i("CANDIDATE_TOP_K", 5))
    association_signal: str = field(default_factory=lambda: _s("ASSOCIATION_SIGNAL", "embedding"))  # embedding | cross_encoder
    judge: str = field(default_factory=lambda: _s("JUDGE", "anthropic"))  # anthropic | local
    calibrator: str = field(default_factory=lambda: _s("CALIBRATOR", "static"))  # static | learned
    score_log: bool = field(default_factory=lambda: _b("SCORE_LOG", False))
```

- [ ] **Step 2: Document in `.env.example`**

Append after the job-queue block:

```bash
# ── Causal scorer (optional; defaults shown). SCORER=legacy reverts to the old behavior ──
# SCORER=hybrid               # hybrid (embedding assoc + batched judge) | legacy
# CANDIDATE_TOP_K=5           # candidates judged per ingested event
# ASSOCIATION_SIGNAL=embedding # embedding | cross_encoder (placeholder)
# JUDGE=anthropic             # anthropic | local (placeholder)
# CALIBRATOR=static           # static | learned (placeholder)
# SCORE_LOG=false             # log (signals -> outcome) rows for later calibration
```

- [ ] **Step 3: Verify**

Run: `mnemosyne/.venv/bin/python -c "from mnemosyne.config import get_settings as g; s=g(); print(s.scorer, s.candidate_top_k, s.association_signal, s.judge, s.calibrator)"`
Expected: `hybrid 5 embedding anthropic static`

- [ ] **Step 4: Commit**

```bash
git add mnemosyne/config.py .env.example
git commit -m "feat(scorer): config knobs for the hybrid causal scorer"
```

---

## Task 2: Calibration module

**Files:** Create `mnemosyne/pipeline/calibration.py`, Test `mnemosyne/tests/test_calibration.py`

- [ ] **Step 1: Write the failing test**

Create `mnemosyne/tests/test_calibration.py`:

```python
import dataclasses

import pytest

from mnemosyne.config import Settings
from mnemosyne.pipeline.calibration import (
    LearnedCalibrator,
    StaticCalibrator,
    make_calibrator,
)
from mnemosyne.pipeline.causal import blend


def _s(**kw):
    return dataclasses.replace(Settings(), **kw)


def test_static_calibrator_equals_legacy_blend():
    s = _s()
    c = StaticCalibrator(s)
    for t, a, l in [(1.0, 0.0, 0.0), (0.5, 0.5, 0.5), (0.2, 0.9, 0.7)]:
        assert c.confidence(t, a, l) == pytest.approx(blend(t, a, l, s))
    assert c.threshold() == s.confidence_threshold


def test_make_calibrator_default_is_static():
    assert isinstance(make_calibrator(_s()), StaticCalibrator)


def test_learned_calibrator_is_a_placeholder():
    with pytest.raises(NotImplementedError):
        LearnedCalibrator(_s()).confidence(0.5, 0.5, 0.5)
    with pytest.raises(NotImplementedError):
        make_calibrator(_s(calibrator="learned"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mnemosyne.pipeline.calibration'`

- [ ] **Step 3: Implement**

Create `mnemosyne/pipeline/calibration.py`:

```python
"""Confidence calibration: turn the three signals into a final 0..1 confidence and
expose the storage threshold. StaticCalibrator reproduces the legacy weighted blend;
LearnedCalibrator is a placeholder for a model trained on confirmed edges (spec §6/§11)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..config import Settings


@runtime_checkable
class Calibrator(Protocol):
    def confidence(self, temporal: float, association: float, llm: float) -> float: ...

    def threshold(self) -> float: ...


class StaticCalibrator:
    """Fixed weighted blend (identical to the legacy `causal.blend`) + fixed threshold."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def confidence(self, temporal: float, association: float, llm: float) -> float:
        s = self._s
        return (
            s.weight_temporal * temporal
            + s.weight_linguistic * association
            + s.weight_llm * llm
        )

    def threshold(self) -> float:
        return self._s.confidence_threshold


class LearnedCalibrator:
    """Placeholder: a learned blend (e.g. logistic over confirmed edges). Not yet trained."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def confidence(self, temporal: float, association: float, llm: float) -> float:
        raise NotImplementedError("LearnedCalibrator: not yet trained (spec §6/§11)")

    def threshold(self) -> float:
        raise NotImplementedError("LearnedCalibrator: not yet trained (spec §6/§11)")


def make_calibrator(settings: Settings) -> Calibrator:
    if settings.calibrator == "learned":
        c = LearnedCalibrator(settings)
        c.threshold()  # fail fast: placeholder is not usable
        return c
    return StaticCalibrator(settings)
```

- [ ] **Step 4: Run to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_calibration.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add mnemosyne/pipeline/calibration.py mnemosyne/tests/test_calibration.py
git commit -m "feat(scorer): Calibrator (StaticCalibrator == legacy blend) + learned placeholder"
```

---

## Task 3: Association signals + candidate selection

**Files:** Create `mnemosyne/pipeline/signals.py`, Test `mnemosyne/tests/test_signals.py`

- [ ] **Step 1: Write the failing test**

Create `mnemosyne/tests/test_signals.py`:

```python
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from mnemosyne.config import Settings
from mnemosyne.models import Event
from mnemosyne.pipeline.signals import (
    CrossEncoderCausal,
    EmbeddingCosine,
    make_association,
    select_candidates,
)

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


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


def test_embedding_cosine_passes_through_the_cosine():
    assert EmbeddingCosine().score(_ev("a", 5), _ev("b", 0), 0.73) == 0.73


def test_cross_encoder_is_a_placeholder():
    with pytest.raises(NotImplementedError):
        CrossEncoderCausal().score(_ev("a", 5), _ev("b", 0), 0.5)
    with pytest.raises(NotImplementedError):
        make_association(dataclasses.replace(Settings(), association_signal="cross_encoder"))


def test_select_candidates_filters_by_time_and_caps_at_top_k():
    effect = _ev("E", 0)
    causes = [_ev("c1", 10), _ev("c2", 5), _ev("c3", 1)]
    future = _ev("future", -5)  # occurs AFTER the effect -> must be pruned
    graph = FakeGraph(causes + [future, effect])
    # cosine order: future(0.99) c1(0.9) c2(0.8) c3(0.7) self(1.0)
    vector = FakeVector([
        ("E", 1.0, {}), ("future", 0.99, {}), ("c1", 0.9, {}),
        ("c2", 0.8, {}), ("c3", 0.7, {}),
    ])
    s = dataclasses.replace(Settings(), candidate_top_k=2)
    cands = select_candidates(effect, graph, vector, s)

    ids = [c.cause.id for c in cands]
    assert "E" not in ids and "future" not in ids       # self + future pruned
    assert len(cands) == 2                                # capped at top_k
    assert all(c.temporal > 0 and 0 <= c.cosine <= 1 for c in cands)


def test_select_candidates_empty_when_effect_has_no_embedding():
    effect = _ev("E", 0).model_copy(update={"embedding": None})  # Event is pydantic, not a dataclass
    assert select_candidates(effect, FakeGraph([]), FakeVector([]), Settings()) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mnemosyne.pipeline.signals'`

- [ ] **Step 3: Implement**

Create `mnemosyne/pipeline/signals.py`:

```python
"""Association signal + candidate selection for the hybrid scorer.

The default association is the embedding cosine (already computed by the candidate
vector search). `CrossEncoderCausal` is a placeholder for a local cross-encoder/NLI model
(spec §6/§11). `select_candidates` returns the temporally-eligible, top-K associated
prior events for an effect — bounding how many pairs the LLM has to judge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..config import Settings
from ..interfaces import GraphStore, VectorStore
from ..models import Event
from .causal import temporal_score


@dataclass
class Candidate:
    cause: Event
    temporal: float
    cosine: float


@runtime_checkable
class AssociationSignal(Protocol):
    def score(self, cause: Event, effect: Event, cosine: float) -> float: ...


class EmbeddingCosine:
    """Default: reuse the embedding cosine produced by the candidate vector search."""

    def score(self, cause: Event, effect: Event, cosine: float) -> float:
        return cosine


class CrossEncoderCausal:
    """Placeholder: a local cross-encoder/NLI causal score from (cause.text, effect.text)."""

    def score(self, cause: Event, effect: Event, cosine: float) -> float:
        raise NotImplementedError("CrossEncoderCausal: local cross-encoder not yet wired (spec §6/§11)")


def make_association(settings: Settings) -> AssociationSignal:
    if settings.association_signal == "cross_encoder":
        return CrossEncoderCausal()
    return EmbeddingCosine()


def select_candidates(
    effect: Event, graph: GraphStore, vector: VectorStore, settings: Settings
) -> list[Candidate]:
    """Top-K prior, temporally-eligible events most associated (by cosine) with `effect`."""
    if not effect.embedding:
        return []
    k_search = max(settings.candidate_top_k * 4, 20)
    cands: list[Candidate] = []
    for cid, cosine, _payload in vector.search(effect.embedding, k_search):
        if cid == effect.id:
            continue
        cause = graph.get_event(cid)
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
        cands.append(Candidate(cause=cause, temporal=t, cosine=float(cosine)))
    cands.sort(key=lambda c: c.temporal * c.cosine, reverse=True)
    return cands[: settings.candidate_top_k]
```

- [ ] **Step 4: Run to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_signals.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add mnemosyne/pipeline/signals.py mnemosyne/tests/test_signals.py
git commit -m "feat(scorer): embedding-association signal + top-K candidate selection"
```

---

## Task 4: Batched causal judge

**Files:** Modify `mnemosyne/interfaces.py`, `mnemosyne/llm/prompts.py`, `mnemosyne/llm/anthropic_client.py`; Test `mnemosyne/tests/test_batch_judge.py`

- [ ] **Step 1: Write the failing test** (tests the pure parser — no API)

Create `mnemosyne/tests/test_batch_judge.py`:

```python
from datetime import datetime, timezone

from mnemosyne.llm.anthropic_client import _parse_batch
from mnemosyne.models import Event

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _ev(id_):
    return Event(id=id_, summary=id_, detail="", occurred_at=NOW, learned_at=NOW, tags=[])


def test_parse_batch_maps_by_cause_id_and_fills_missing_with_neutral():
    causes = [_ev("a"), _ev("b"), _ev("c")]
    out = {
        "judgments": [
            {"cause_id": "a", "relation": "caused", "confidence": 0.8, "justification": "x"},
            {"cause_id": "b", "relation": "none", "confidence": 0.1, "justification": "y"},
            # "c" omitted by the model -> must default to neutral
        ]
    }
    parsed = _parse_batch(out, causes)
    assert [p["cause_id"] for p in parsed] == ["a", "b", "c"]
    assert parsed[0]["relation"] == "caused" and parsed[0]["confidence"] == 0.8
    assert parsed[2]["relation"] == "none" and parsed[2]["confidence"] == 0.0


def test_parse_batch_handles_garbage():
    causes = [_ev("a")]
    parsed = _parse_batch({}, causes)
    assert parsed == [{"cause_id": "a", "relation": "none", "confidence": 0.0, "justification": ""}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_batch_judge.py -v`
Expected: FAIL — `ImportError: cannot import name '_parse_batch'`

- [ ] **Step 3a: Add the interface method**

In `mnemosyne/interfaces.py`, inside the `LLMClient` Protocol, after the `judge_causality` method, add:

```python
    def judge_causality_batch(
        self, effect: Event, causes: list[Event]
    ) -> list[dict[str, Any]]:
        """Stage B, batched: judge several candidate causes for one effect in a single
        call. Returns one dict per cause with keys cause_id/relation/confidence/justification."""
        ...
```

- [ ] **Step 3b: Add the batched prompt + tool**

In `mnemosyne/llm/prompts.py`, append:

```python
JUDGMENT_BATCH_SYSTEM = """You judge whether each candidate cause causally CONTRIBUTED to \
ONE effect event. Approximate causality (temporal precedence + association + your judgment), \
not proof. Be conservative: if the effect would plausibly have happened regardless of a \
candidate, mark that candidate "none" with low confidence.

For EACH candidate (identified by its cause_id) emit a judgment with:
- relation: "caused" | "triggered" | "led_to" | "enabled" | "none"
- confidence: 0..1
- justification: ONE sentence
Return ONLY via the emit_judgments tool, one entry per candidate cause_id."""

JUDGMENT_BATCH_TOOL = {
    "name": "emit_judgments",
    "description": "Emit one causal judgment per candidate cause.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cause_id": {"type": "string"},
                        "relation": {
                            "type": "string",
                            "enum": ["caused", "triggered", "led_to", "enabled", "none"],
                        },
                        "confidence": {"type": "number"},
                        "justification": {"type": "string"},
                    },
                    "required": ["cause_id", "relation", "confidence", "justification"],
                },
            }
        },
        "required": ["judgments"],
    },
}
```

- [ ] **Step 3c: Implement the parser + method**

In `mnemosyne/llm/anthropic_client.py`, add a module-level function (after the imports, before the class):

```python
def _parse_batch(out: dict[str, Any], causes: list[Event]) -> list[dict[str, Any]]:
    """Map the model's judgments back onto every cause id; fill missing with neutral."""
    by_id: dict[str, dict[str, Any]] = {}
    for j in out.get("judgments", []) or []:
        cid = str(j.get("cause_id", ""))
        if cid:
            by_id[cid] = {
                "cause_id": cid,
                "relation": j.get("relation", "none"),
                "confidence": float(j.get("confidence", 0.0) or 0.0),
                "justification": j.get("justification", ""),
            }
    return [
        by_id.get(
            c.id,
            {"cause_id": c.id, "relation": "none", "confidence": 0.0, "justification": ""},
        )
        for c in causes
    ]
```

Then add this method to `AnthropicLLM` (after `judge_causality`):

```python
    def judge_causality_batch(
        self, effect: Event, causes: list[Event]
    ) -> list[dict[str, Any]]:
        if not causes:
            return []
        lines = [
            "Effect (B):",
            f"  id={effect.id} occurred_at={effect.occurred_at.isoformat()}",
            f"  summary: {effect.summary}\n  detail: {effect.detail}\n  tags: {effect.tags}",
            "",
            "Candidate causes (each may or may not have contributed to B):",
        ]
        for c in causes:
            lines.append(
                f"  - cause_id={c.id} occurred_at={c.occurred_at.isoformat()} "
                f"summary={c.summary!r} tags={c.tags}"
            )
        out = self._tool_call(
            self._judgment_model,
            prompts.JUDGMENT_BATCH_SYSTEM,
            "\n".join(lines),
            prompts.JUDGMENT_BATCH_TOOL,
            max_tokens=1024,
        )
        return _parse_batch(out, causes)
```

- [ ] **Step 4: Run to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_batch_judge.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add mnemosyne/interfaces.py mnemosyne/llm/prompts.py mnemosyne/llm/anthropic_client.py mnemosyne/tests/test_batch_judge.py
git commit -m "feat(scorer): batched causal judge (one Haiku call per effect)"
```

---

## Task 5: Hybrid orchestration (`infer_edges_hybrid`)

**Files:** Create `mnemosyne/pipeline/scoring.py`, Test `mnemosyne/tests/test_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `mnemosyne/tests/test_scoring.py`:

```python
import dataclasses
from datetime import datetime, timedelta, timezone

from mnemosyne.config import Settings
from mnemosyne.models import Event
from mnemosyne.pipeline.scoring import infer_edges_hybrid

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _ev(id_, minutes_before):
    return Event(
        id=id_, summary=id_, detail="", occurred_at=NOW - timedelta(minutes=minutes_before),
        learned_at=NOW, tags=[], embedding=[1.0, 0.0],
    )


class FakeGraph:
    def __init__(self, events):
        self._by_id = {e.id: e for e in events}

    def get_event(self, event_id):
        return self._by_id.get(event_id)


class FakeVector:
    def __init__(self, hits):
        self._hits = hits

    def search(self, vector, k):
        return self._hits[:k]


class FakeJudge:
    def __init__(self):
        self.calls = 0

    def judge_causality_batch(self, effect, causes):
        self.calls += 1  # MUST be one call for all candidates
        return [
            {"cause_id": c.id, "relation": "caused", "confidence": 0.9, "justification": "x"}
            for c in causes
        ]


def _setup():
    effect = _ev("E", 0)
    c1, c2 = _ev("c1", 10), _ev("c2", 5)
    graph = FakeGraph([effect, c1, c2])
    vector = FakeVector([("E", 1.0, {}), ("c1", 0.8, {}), ("c2", 0.7, {})])
    return effect, graph, vector


def test_hybrid_one_batched_call_and_blended_edges():
    effect, graph, vector = _setup()
    judge = FakeJudge()
    s = dataclasses.replace(Settings(), candidate_top_k=5)
    edges = infer_edges_hybrid(effect, graph=graph, vector=vector, settings=s, llm=judge)

    assert judge.calls == 1                       # bounded: ONE call, not per-pair
    assert {e.cause_id for e in edges} == {"c1", "c2"}
    assert all(e.effect_id == "E" for e in edges)
    # blend = 0.3*temporal + 0.2*cosine + 0.5*0.9 ; with llm=0.9 this clears 0.55
    assert all(e.confidence > 0.55 for e in edges)


def test_hybrid_without_llm_renormalizes_and_still_builds_edges():
    effect, graph, vector = _setup()
    s = dataclasses.replace(Settings(), candidate_top_k=5)
    edges = infer_edges_hybrid(effect, graph=graph, vector=vector, settings=s, llm=None)
    assert {e.cause_id for e in edges} == {"c1", "c2"}
    # no-LLM: (0.3*t + 0.2*cosine)/(0.3+0.2) -> in (0,1]
    assert all(0.0 < e.confidence <= 1.0 for e in edges)


def test_hybrid_empty_when_no_candidates():
    effect = _ev("E", 0)
    edges = infer_edges_hybrid(effect, graph=FakeGraph([effect]), vector=FakeVector([("E", 1.0, {})]),
                               settings=Settings(), llm=None)
    assert edges == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mnemosyne.pipeline.scoring'`

- [ ] **Step 3: Implement**

Create `mnemosyne/pipeline/scoring.py`:

```python
"""Hybrid causal-edge inference: select top-K associated prior candidates, judge them in
ONE batched LLM call, blend (temporal + association + llm) via the calibrator, and build
edges (below-threshold edges are kept — stored but excluded from default traversal).

`LocalCausalModel` is a placeholder judge (spec §6/§11)."""

from __future__ import annotations

from typing import Any, Optional

from ..config import Settings
from ..interfaces import GraphStore, LLMClient, VectorStore
from ..models import CAUSAL_RELATIONS, RELATION_CAUSED, CausalEdge, Event, build_causal_edge
from .calibration import make_calibrator
from .signals import make_association, select_candidates


class LocalCausalModel:
    """Placeholder local judge (e.g. on the vLLM/MI300X infra). Not yet wired."""

    def judge_causality_batch(self, effect: Event, causes: list[Event]) -> list[dict[str, Any]]:
        raise NotImplementedError("LocalCausalModel: local judge not yet wired (spec §6/§11)")


def infer_edges_hybrid(
    effect: Event,
    *,
    graph: GraphStore,
    vector: VectorStore,
    settings: Settings,
    llm: Optional[LLMClient] = None,
) -> list[CausalEdge]:
    if settings.judge == "local":
        raise NotImplementedError("JUDGE=local: local judge not yet wired (spec §6/§11)")

    candidates = select_candidates(effect, graph, vector, settings)
    if not candidates:
        return []

    association = make_association(settings)
    calibrator = make_calibrator(settings)

    judgments: dict[str, dict[str, Any]] = {}
    if llm is not None:
        try:
            for j in llm.judge_causality_batch(effect, [c.cause for c in candidates]):
                judgments[str(j.get("cause_id", ""))] = j
        except Exception:  # noqa: BLE001 — degrade to temporal+association, never crash ingest
            judgments = {}

    wt, wl = settings.weight_temporal, settings.weight_linguistic
    edges: list[CausalEdge] = []
    for c in candidates:
        assoc = association.score(c.cause, effect, c.cosine)
        j = judgments.get(c.cause.id)
        if j is not None:
            relation = j.get("relation", RELATION_CAUSED)
            if relation not in CAUSAL_RELATIONS:  # "none"/unknown -> low blend, stays below threshold
                relation = RELATION_CAUSED
            llm_conf = float(j.get("confidence", 0.0) or 0.0)
            confidence = calibrator.confidence(c.temporal, assoc, llm_conf)
            evidence = f"temporal={c.temporal:.2f}; assoc={assoc:.2f}; llm={llm_conf:.2f}: {j.get('justification','')}"
            method = "temporal+assoc+llm"
        else:
            relation = RELATION_CAUSED
            denom = (wt + wl) or 1.0
            confidence = (wt * c.temporal + wl * assoc) / denom
            evidence = f"temporal={c.temporal:.2f}; assoc={assoc:.2f} (no-LLM)"
            method = "temporal+assoc"
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_scoring.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add mnemosyne/pipeline/scoring.py mnemosyne/tests/test_scoring.py
git commit -m "feat(scorer): hybrid infer_edges (select -> batched judge -> calibrated blend)"
```

---

## Task 6: Wire the service (hybrid default, legacy switch)

**Files:** Modify `mnemosyne/service.py`

- [ ] **Step 1: Add the import**

In `mnemosyne/service.py`, after the line `from .pipeline.causal import infer_edges`, add:

```python
from .pipeline.scoring import infer_edges_hybrid
```

- [ ] **Step 2: Branch the edge-inference in `ingest`**

In `MnemosyneService.ingest`, replace this block:

```python
                window_start = ev.occurred_at - timedelta(seconds=self.settings.temporal_max_window_s)
                candidates = self.graph.candidate_causes(ev, window_start)
                for edge in infer_edges(ev, candidates, settings=self.settings, llm=self.llm):
                    self.graph.add_edge(edge)
                    edges_created.append(edge)
```

with:

```python
                if self.settings.scorer == "legacy":
                    window_start = ev.occurred_at - timedelta(seconds=self.settings.temporal_max_window_s)
                    candidates = self.graph.candidate_causes(ev, window_start)
                    new_edges = infer_edges(ev, candidates, settings=self.settings, llm=self.llm)
                else:
                    new_edges = infer_edges_hybrid(
                        ev, graph=self.graph, vector=self.vector, settings=self.settings, llm=self.llm
                    )
                for edge in new_edges:
                    self.graph.add_edge(edge)
                    edges_created.append(edge)
```

(`timedelta` stays imported — it's still used in the legacy branch.)

- [ ] **Step 3: Verify hybrid ingest end-to-end (needs Neo4j + Qdrant; skips cleanly without)**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_retrieval_causal.py mnemosyne/tests/test_causal_blend.py -v`
Expected: PASS or skip (the `service` fixture uses `llm=None`; hybrid builds edges via the no-LLM path). If Neo4j/Qdrant are down the service tests skip — that is acceptable here; the hybrid unit tests (Task 5) already prove the logic.

- [ ] **Step 4: Commit**

```bash
git add mnemosyne/service.py
git commit -m "feat(scorer): service uses hybrid scoring by default, SCORER=legacy reverts"
```

---

## Task 7: Full verification + legacy-switch check

**Files:** none (verification)

- [ ] **Step 1: New scorer unit tests**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_calibration.py mnemosyne/tests/test_signals.py mnemosyne/tests/test_scoring.py mnemosyne/tests/test_batch_judge.py -v`
Expected: all PASS, no Neo4j/Qdrant/LLM needed.

- [ ] **Step 2: Full suite (hybrid default)**

Run: `mnemosyne/.venv/bin/python -m pytest mnemosyne/tests -q`
Expected: all pass or skip (live-LLM + destructive-reset skip without flags). Confirm no failures.

- [ ] **Step 3: Legacy switch still reproduces the old path**

Run: `SCORER=legacy mnemosyne/.venv/bin/python -m pytest mnemosyne/tests/test_causal_blend.py mnemosyne/tests/test_linguistic_signal.py mnemosyne/tests/test_temporal_signal.py -v`
Expected: all PASS (the legacy functions are untouched).

- [ ] **Step 4: Manual smoke (optional, needs the live stack + ANTHROPIC key)**

Restart the backend, re-ingest the demo Slack messages, ask the causal query, and confirm edges still form with sensible confidences. Compare hybrid vs `SCORER=legacy` to see the difference. If hybrid shifts the demo unfavorably, set `SCORER=legacy` in `.env` while iterating.

- [ ] **Step 5: Commit (if anything adjusted)**

```bash
git add -A
git commit -m "test(scorer): verify hybrid scorer + legacy switch" --allow-empty
```

---

## Notes for the implementer

- **Do not modify `mnemosyne/pipeline/causal.py`** — `temporal_score`, `linguistic_score`, `blend`, `score_pair`, `infer_edges` stay as-is (legacy path + existing tests depend on them). `signals.py` imports `temporal_score` from it; `scoring.py` imports `causal` only transitively via `signals`/`calibration`, so there is no import cycle.
- The hybrid path's **no-LLM branch renormalizes** `(wt·t + wl·assoc)/(wt+wl)` exactly like the legacy `score_pair` no-LLM branch, so edges still form (and clear thresholds in retrieval tests) when `llm=None`.
- Placeholders (`CrossEncoderCausal`, `LearnedCalibrator`, `LocalCausalModel`, `JUDGE=local`) all `raise NotImplementedError` and are unreachable on default config.
- Tasks 2–5 are pure unit tests with fakes; Task 6 is the only one whose end-to-end check wants the live stores (and skips cleanly without them).
- **`SCORE_LOG` is config-only this round** — the knob exists (Task 1) but the actual `(signals → outcome)` logging is deferred to the future calibration work (spec §11). Don't implement the JSONL writer now; YAGNI until the `LearnedCalibrator` is built.
- `Event` is a **pydantic** `BaseModel`: build with `Event(id=..., summary=..., occurred_at=..., ...)` and copy with `.model_copy(update={...})` — never `dataclasses.replace` (that's only for the frozen `Settings` dataclass).
