"""Core data model.

Two things are ground truth:
  * ``Event``       — an immutable, bi-temporal, timestamped happening.
  * ``CausalEdge``  — a directed cause->effect edge (the novel index).

Invariants enforced here (see also the graph store):
  * An edge is valid only if ``cause.occurred_at <= effect.occurred_at``.
  * ``confidence`` is mandatory and bounded to [0, 1]; an edge with no confidence
    is never constructed.
  * The event log is append-only — we never mutate an event in place; corrections
    are new events that *supersede* (a ``SUPERSEDES`` relation).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# Relation vocabulary for causal/episodic edges.
RELATION_CAUSED = "caused"
RELATION_TRIGGERED = "triggered"
RELATION_LED_TO = "led_to"
RELATION_ENABLED = "enabled"
RELATION_SUPERSEDES = "supersedes"
CAUSAL_RELATIONS = {RELATION_CAUSED, RELATION_TRIGGERED, RELATION_LED_TO, RELATION_ENABLED}

# How an edge's confidence was derived.
METHOD_BLEND = "temporal+association+llm"
METHOD_NO_LLM = "temporal+association"
METHOD_MANUAL = "manual"


class CausalityViolation(ValueError):
    """Raised when an edge would place a cause after its effect."""


def _new_id() -> str:
    return str(uuid.uuid4())


def _utc(dt: datetime) -> datetime:
    """Normalize any datetime to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Event(BaseModel):
    """The only thing we store as ground truth.

    Bi-temporal on purpose — do not collapse ``occurred_at`` and ``learned_at`` into
    one timestamp. ``occurred_at`` is when it happened in the world; ``learned_at`` is
    when the system ingested it. Storing both from day one is what makes time-travel
    queries ("what did we believe at T?") possible later.
    """

    id: str = Field(default_factory=_new_id)
    summary: str                       # one-line natural language
    detail: str = ""                   # full text
    occurred_at: datetime              # when the event happened in the world
    learned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    embedding: Optional[list[float]] = None  # for the anchor step (lives in Qdrant)
    tags: list[str] = Field(default_factory=list)  # extracted entities/topics
    source_id: str = ""                # which document/session it came from

    # --- consolidation (Stage C) ---
    reinforcement_count: int = 0       # independent confirmations seen
    salience: float = 1.0              # decays with age unless reinforced

    @field_validator("occurred_at", "learned_at")
    @classmethod
    def _normalize_tz(cls, v: datetime) -> datetime:
        return _utc(v)

    def embed_text(self) -> str:
        """Text used for the semantic embedding (summary + detail)."""
        return f"{self.summary}\n{self.detail}".strip()


class CausalEdge(BaseModel):
    """The novel index: a directed cause->effect edge.

    We never store an edge without ``confidence`` and ``evidence`` — unexplained
    edges are useless and erode trust.
    """

    id: str = Field(default_factory=_new_id)
    cause_id: str
    effect_id: str
    relation: str = RELATION_CAUSED
    confidence: float                  # 0..1, REQUIRED
    evidence: str                      # why we think this is causal (the cue/justification)
    method: str = METHOD_BLEND         # how confidence was derived
    occurred_delta_s: int              # effect.occurred_at - cause.occurred_at, seconds

    @field_validator("confidence")
    @classmethod
    def _conf_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {v}")
        return v

    @model_validator(mode="after")
    def _causes_precede_effects(self) -> "CausalEdge":
        # Hard invariant, not a soft check: a cause cannot occur after its effect.
        if self.occurred_delta_s < 0:
            raise CausalityViolation(
                f"cause must precede effect: occurred_delta_s={self.occurred_delta_s} (<0)"
            )
        return self


def build_causal_edge(
    cause: Event,
    effect: Event,
    *,
    relation: str,
    confidence: float,
    evidence: str,
    method: str = METHOD_BLEND,
) -> CausalEdge:
    """Construct an edge from two events, computing the temporal delta and enforcing
    the causality invariant. Raises ``CausalityViolation`` if cause occurs after effect.
    """
    delta = int((_utc(effect.occurred_at) - _utc(cause.occurred_at)).total_seconds())
    if delta < 0:
        raise CausalityViolation(
            f"cannot create edge {cause.id} -> {effect.id}: "
            f"cause occurred_at ({cause.occurred_at.isoformat()}) is after "
            f"effect occurred_at ({effect.occurred_at.isoformat()})"
        )
    return CausalEdge(
        cause_id=cause.id,
        effect_id=effect.id,
        relation=relation,
        confidence=confidence,
        evidence=evidence,
        method=method,
        occurred_delta_s=delta,
    )
