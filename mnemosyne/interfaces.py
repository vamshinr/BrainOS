"""Protocol interfaces for the swappable backends.

Business logic depends on these Protocols, never on Neo4j / Qdrant / a specific
embedding model directly. That is what keeps the stack swappable (interfaces over
implementations).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol, runtime_checkable

from .models import CausalEdge, Event


@runtime_checkable
class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorStore(Protocol):
    def ensure_collection(self, dim: int) -> None: ...

    def upsert(self, event_id: str, vector: list[float], payload: dict[str, Any]) -> None: ...

    def search(
        self, vector: list[float], k: int
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Return [(event_id, score, payload)] ordered by descending similarity."""
        ...

    def delete(self, event_id: str) -> None: ...

    def count(self) -> int: ...

    def clear(self) -> None: ...

    def clear_all(self) -> None:
        """Blanket wipe: delete all points from EVERY collection (not just the
        configured one). Used by the destructive /reset endpoint."""
        ...


@runtime_checkable
class GraphStore(Protocol):
    # --- writes ---
    def add_event(self, event: Event) -> None: ...

    def add_edge(self, edge: CausalEdge) -> None: ...

    def increment_reinforcement(self, event_id: str, delta: int = 1) -> int: ...

    def update_salience(self, event_id: str, salience: float) -> None: ...

    def bump_edge_confidence(self, event_id: str, amount: float, cap: float = 1.0) -> None:
        """Raise confidence on every edge incident to ``event_id`` (capped)."""
        ...

    # --- reads ---
    def get_event(self, event_id: str) -> Optional[Event]: ...

    def event_exists(self, event_id: str) -> bool: ...

    def incoming_edges(self, effect_id: str, min_confidence: float = 0.0) -> list[CausalEdge]: ...

    def outgoing_edges(self, cause_id: str, min_confidence: float = 0.0) -> list[CausalEdge]: ...

    def edges_for_event(self, event_id: str) -> list[CausalEdge]: ...

    def candidate_causes(
        self, effect: Event, window_start: datetime, exclude_ids: Optional[set[str]] = None
    ) -> list[Event]:
        """Events whose occurred_at is in [window_start, effect.occurred_at] (inclusive),
        i.e. plausible causes by temporal precedence."""
        ...

    def all_events(self) -> list[Event]: ...

    def all_edges(self) -> list[CausalEdge]: ...

    # --- lifecycle ---
    def clear(self) -> None: ...

    def clear_all(self) -> None:
        """Blanket wipe: every node + relationship in the database, regardless of
        label. Used by the destructive /reset endpoint."""
        ...

    def close(self) -> None: ...


@runtime_checkable
class LLMClient(Protocol):
    def extract_events(
        self, text: str, reference_time: datetime, context: str = ""
    ) -> list[dict[str, Any]]:
        """Stage A: return a list of dicts with keys summary/detail/occurred_at/tags.
        ``context`` is optional read-only preceding text (sliding window) the model
        should use for reference but NOT extract events from."""
        ...

    def judge_causality(self, cause: Event, effect: Event) -> dict[str, Any]:
        """Stage B signal 3: return {relation, confidence, justification}."""
        ...

    def synthesize(self, query: str, ordered_chain: list[dict[str, Any]]) -> str:
        """Retrieval step 5: produce the 'why' narrative citing event ids + timestamps."""
        ...
