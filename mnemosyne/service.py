"""MnemosyneService — orchestrates ingest and retrieval over the swappable backends.

Business logic lives here and in ``pipeline/*``; it depends only on the Protocol
interfaces, never on Neo4j/Qdrant specifics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .config import Settings
from .interfaces import Embedder, GraphStore, LLMClient, VectorStore
from .models import CausalEdge, Event, build_causal_edge
from .pipeline.causal import infer_edges
from .pipeline.consolidation import find_duplicate, reinforce, salience
from .pipeline.extraction import extract_events
from .pipeline.retrieval import retrieve_associative, retrieve_causal


def _edge_to_dict(e: CausalEdge) -> dict[str, Any]:
    return {
        "id": e.id,
        "cause_id": e.cause_id,
        "effect_id": e.effect_id,
        "relation": e.relation,
        "confidence": e.confidence,
        "evidence": e.evidence,
        "method": e.method,
        "occurred_delta_s": e.occurred_delta_s,
    }


def _vector_payload(ev: Event) -> dict[str, Any]:
    return {
        "summary": ev.summary,
        "tags": ev.tags,
        "occurred_at": ev.occurred_at.isoformat(),
        "source_id": ev.source_id,
    }


class MnemosyneService:
    def __init__(
        self,
        *,
        graph: GraphStore,
        vector: VectorStore,
        embedder: Embedder,
        settings: Settings,
        llm: Optional[LLMClient] = None,
    ) -> None:
        self.graph = graph
        self.vector = vector
        self.embedder = embedder
        self.settings = settings
        self.llm = llm
        self.vector.ensure_collection(embedder.dim)

    # ------------------------------------------------------------------- ingest
    def ingest(
        self,
        text: str,
        *,
        source_id: str = "",
        reference_time: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("ingest requires an Anthropic API key for event extraction")
        ref = reference_time or datetime.now(timezone.utc)
        extracted = extract_events(
            text,
            source_id=source_id,
            reference_time=ref,
            llm=self.llm,
            embedder=self.embedder,
        )

        created: list[Event] = []
        reinforced: list[dict[str, Any]] = []
        edges_created: list[CausalEdge] = []

        for ev in extracted:
            dup_id = find_duplicate(ev, self.vector, self.graph, self.settings)
            if dup_id is not None:
                count = reinforce(dup_id, self.graph, self.settings, now=ref)
                reinforced.append({"event_id": dup_id, "reinforcement_count": count})
                continue

            self.graph.add_event(ev)
            self.vector.upsert(ev.id, ev.embedding or [], _vector_payload(ev))
            created.append(ev)

            window_start = ev.occurred_at - timedelta(seconds=self.settings.temporal_max_window_s)
            candidates = self.graph.candidate_causes(ev, window_start)
            for edge in infer_edges(ev, candidates, settings=self.settings, llm=self.llm):
                self.graph.add_edge(edge)
                edges_created.append(edge)

        return {
            "events_created": [e.id for e in created],
            "events_reinforced": reinforced,
            "edges_created": [_edge_to_dict(e) for e in edges_created],
            "counts": {
                "created": len(created),
                "reinforced": len(reinforced),
                "edges": len(edges_created),
            },
        }

    def add_manual_edge(
        self, cause_id: str, effect_id: str, *, relation: str, confidence: float = 1.0, evidence: str = "manual"
    ) -> dict[str, Any]:
        """Create an operator-asserted edge. Enforces the causality invariant:
        raises CausalityViolation if the cause occurs after the effect."""
        cause = self.graph.get_event(cause_id)
        effect = self.graph.get_event(effect_id)
        if cause is None or effect is None:
            raise ValueError("cause or effect event not found")
        edge = build_causal_edge(
            cause, effect, relation=relation, confidence=confidence, evidence=evidence, method="manual"
        )
        self.graph.add_edge(edge)
        return _edge_to_dict(edge)

    # ----------------------------------------------------------------- retrieve
    def retrieve(self, query: str, *, k: int = 5, mode: str = "causal") -> dict[str, Any]:
        if mode == "associative":
            return retrieve_associative(
                query, k, embedder=self.embedder, vector=self.vector, graph=self.graph, settings=self.settings
            )
        return retrieve_causal(
            query,
            k,
            embedder=self.embedder,
            vector=self.vector,
            graph=self.graph,
            settings=self.settings,
            llm=self.llm,
        )

    # -------------------------------------------------------------- inspection
    def graph_dump(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        events = self.graph.all_events()
        return {
            "events": [
                {
                    "id": e.id,
                    "summary": e.summary,
                    "occurred_at": e.occurred_at.isoformat(),
                    "learned_at": e.learned_at.isoformat(),
                    "tags": e.tags,
                    "source_id": e.source_id,
                    "reinforcement_count": e.reinforcement_count,
                    "salience": round(salience(e, now, self.settings.salience_half_life_s), 4),
                }
                for e in events
            ],
            "edges": [_edge_to_dict(e) for e in self.graph.all_edges()],
        }

    def get_event(self, event_id: str) -> Optional[dict[str, Any]]:
        ev = self.graph.get_event(event_id)
        if ev is None:
            return None
        now = datetime.now(timezone.utc)
        return {
            "event": {
                "id": ev.id,
                "summary": ev.summary,
                "detail": ev.detail,
                "occurred_at": ev.occurred_at.isoformat(),
                "learned_at": ev.learned_at.isoformat(),
                "tags": ev.tags,
                "source_id": ev.source_id,
                "reinforcement_count": ev.reinforcement_count,
                "salience": round(salience(ev, now, self.settings.salience_half_life_s), 4),
            },
            "incoming_edges": [_edge_to_dict(e) for e in self.graph.incoming_edges(event_id)],
            "outgoing_edges": [_edge_to_dict(e) for e in self.graph.outgoing_edges(event_id)],
        }

    def health(self) -> dict[str, Any]:
        status: dict[str, Any] = {"status": "ok"}
        try:
            self.graph.verify()  # type: ignore[attr-defined]
            status["neo4j"] = "connected"
        except Exception as exc:  # noqa: BLE001
            status["status"] = "degraded"
            status["neo4j"] = f"error: {exc}"
        try:
            status["vector_points"] = self.vector.count()
        except Exception as exc:  # noqa: BLE001
            status["status"] = "degraded"
            status["vector_points"] = f"error: {exc}"
        status["llm"] = "anthropic" if self.llm is not None else "disabled (no api key)"
        status["embedding_dim"] = self.embedder.dim
        return status

    def reset(self) -> dict[str, Any]:
        """Clear ALL stored events + edges from both stores (this app namespace only:
        the configured event label in Neo4j and the configured Qdrant collection)."""
        events = len(self.graph.all_events())
        edges = len(self.graph.all_edges())
        self.graph.clear()
        self.vector.clear()
        return {"ok": True, "cleared": {"events": events, "edges": edges}}

    def close(self) -> None:
        self.graph.close()
