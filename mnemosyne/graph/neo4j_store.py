"""Neo4j-backed graph store — the only graph backend (no NetworkX, no in-memory stub).

Schema:
    (c:Event)-[:CAUSES {id, cause_id, effect_id, relation, confidence,
                        evidence, method, occurred_delta_s}]->(e:Event)

Events are append-only: ``add_event`` uses MERGE ... ON CREATE so re-ingesting the
same id never mutates stored facts. The only permitted in-place writes are the
consolidation counters (reinforcement_count, salience) and edge-confidence bumps.

The node label is configurable so tests can run on an isolated namespace
(e.g. ``TestEvent``) without touching real data.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import GraphDatabase
from neo4j.time import DateTime as Neo4jDateTime

from ..models import CausalEdge, Event

_SAFE_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _to_dt(value: Any) -> datetime:
    if isinstance(value, Neo4jDateTime):
        return value.to_native().astimezone(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    # ISO string fallback
    return datetime.fromisoformat(str(value)).astimezone(timezone.utc)


class Neo4jGraphStore:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        *,
        database: str = "neo4j",
        event_label: str = "Event",
    ) -> None:
        if not _SAFE_LABEL.match(event_label):
            raise ValueError(f"unsafe event_label: {event_label!r}")
        self._label = event_label
        self._database = database
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_constraints()

    # ------------------------------------------------------------------ lifecycle
    def _run(self, cypher: str, **params):
        with self._driver.session(database=self._database) as session:
            return list(session.run(cypher, **params))

    def _ensure_constraints(self) -> None:
        self._run(
            f"CREATE CONSTRAINT mnemosyne_{self._label}_id IF NOT EXISTS "
            f"FOR (e:{self._label}) REQUIRE e.id IS UNIQUE"
        )

    def verify(self) -> None:
        """Raise if the database is unreachable / auth fails."""
        self._driver.verify_connectivity()

    def close(self) -> None:
        self._driver.close()

    # --------------------------------------------------------------------- writes
    def add_event(self, event: Event) -> None:
        # MERGE ... ON CREATE keeps the log append-only: an existing id is never mutated.
        self._run(
            f"MERGE (e:{self._label} {{id: $id}}) "
            f"ON CREATE SET e.summary=$summary, e.detail=$detail, "
            f"e.occurred_at=$occurred_at, e.learned_at=$learned_at, e.tags=$tags, "
            f"e.source_id=$source_id, e.reinforcement_count=$rc, e.salience=$salience",
            id=event.id,
            summary=event.summary,
            detail=event.detail,
            occurred_at=event.occurred_at,
            learned_at=event.learned_at,
            tags=event.tags,
            source_id=event.source_id,
            rc=event.reinforcement_count,
            salience=event.salience,
        )

    def add_edge(self, edge: CausalEdge) -> None:
        rows = self._run(
            f"MATCH (c:{self._label} {{id: $cause_id}}), (e:{self._label} {{id: $effect_id}}) "
            f"MERGE (c)-[r:CAUSES {{id: $id}}]->(e) "
            f"ON CREATE SET r.cause_id=$cause_id, r.effect_id=$effect_id, "
            f"r.relation=$relation, r.confidence=$confidence, r.evidence=$evidence, "
            f"r.method=$method, r.occurred_delta_s=$delta "
            f"RETURN r.id AS id",
            id=edge.id,
            cause_id=edge.cause_id,
            effect_id=edge.effect_id,
            relation=edge.relation,
            confidence=edge.confidence,
            evidence=edge.evidence,
            method=edge.method,
            delta=edge.occurred_delta_s,
        )
        if not rows:
            raise ValueError(
                f"add_edge: cause {edge.cause_id} or effect {edge.effect_id} not found"
            )

    def increment_reinforcement(self, event_id: str, delta: int = 1) -> int:
        rows = self._run(
            f"MATCH (e:{self._label} {{id: $id}}) "
            f"SET e.reinforcement_count = coalesce(e.reinforcement_count, 0) + $delta "
            f"RETURN e.reinforcement_count AS rc",
            id=event_id,
            delta=delta,
        )
        return int(rows[0]["rc"]) if rows else 0

    def update_salience(self, event_id: str, salience: float) -> None:
        self._run(
            f"MATCH (e:{self._label} {{id: $id}}) SET e.salience = $salience",
            id=event_id,
            salience=salience,
        )

    def bump_edge_confidence(self, event_id: str, amount: float, cap: float = 1.0) -> None:
        # Repeated independent confirmation strengthens the edges touching this event.
        self._run(
            f"MATCH (:{self._label} {{id: $id}})-[r:CAUSES]-() "
            f"SET r.confidence = CASE WHEN r.confidence + $amount > $cap "
            f"THEN $cap ELSE r.confidence + $amount END",
            id=event_id,
            amount=amount,
            cap=cap,
        )

    # ---------------------------------------------------------------------- reads
    def _row_to_event(self, node: Any) -> Event:
        return Event(
            id=node["id"],
            summary=node.get("summary", ""),
            detail=node.get("detail", ""),
            occurred_at=_to_dt(node["occurred_at"]),
            learned_at=_to_dt(node["learned_at"]),
            tags=list(node.get("tags", []) or []),
            source_id=node.get("source_id", ""),
            reinforcement_count=int(node.get("reinforcement_count", 0) or 0),
            salience=float(node.get("salience", 1.0) or 1.0),
        )

    def _row_to_edge(self, rel: Any) -> CausalEdge:
        return CausalEdge(
            id=rel["id"],
            cause_id=rel["cause_id"],
            effect_id=rel["effect_id"],
            relation=rel["relation"],
            confidence=float(rel["confidence"]),
            evidence=rel.get("evidence", ""),
            method=rel.get("method", ""),
            occurred_delta_s=int(rel["occurred_delta_s"]),
        )

    def get_event(self, event_id: str) -> Optional[Event]:
        rows = self._run(
            f"MATCH (e:{self._label} {{id: $id}}) RETURN e", id=event_id
        )
        return self._row_to_event(rows[0]["e"]) if rows else None

    def event_exists(self, event_id: str) -> bool:
        rows = self._run(
            f"MATCH (e:{self._label} {{id: $id}}) RETURN count(e) AS n", id=event_id
        )
        return bool(rows and rows[0]["n"] > 0)

    def incoming_edges(self, effect_id: str, min_confidence: float = 0.0) -> list[CausalEdge]:
        rows = self._run(
            f"MATCH (:{self._label})-[r:CAUSES]->(:{self._label} {{id: $id}}) "
            f"WHERE r.confidence >= $minc RETURN r",
            id=effect_id,
            minc=min_confidence,
        )
        return [self._row_to_edge(row["r"]) for row in rows]

    def outgoing_edges(self, cause_id: str, min_confidence: float = 0.0) -> list[CausalEdge]:
        rows = self._run(
            f"MATCH (:{self._label} {{id: $id}})-[r:CAUSES]->(:{self._label}) "
            f"WHERE r.confidence >= $minc RETURN r",
            id=cause_id,
            minc=min_confidence,
        )
        return [self._row_to_edge(row["r"]) for row in rows]

    def edges_for_event(self, event_id: str) -> list[CausalEdge]:
        rows = self._run(
            f"MATCH (:{self._label} {{id: $id}})-[r:CAUSES]-(:{self._label}) RETURN DISTINCT r",
            id=event_id,
        )
        return [self._row_to_edge(row["r"]) for row in rows]

    def candidate_causes(
        self, effect: Event, window_start: datetime, exclude_ids: Optional[set[str]] = None
    ) -> list[Event]:
        rows = self._run(
            f"MATCH (c:{self._label}) "
            f"WHERE c.occurred_at >= $start AND c.occurred_at <= $end "
            f"AND NOT c.id IN $exclude "
            f"RETURN c ORDER BY c.occurred_at ASC",
            start=window_start,
            end=effect.occurred_at,
            exclude=list((exclude_ids or set()) | {effect.id}),
        )
        return [self._row_to_event(row["c"]) for row in rows]

    def all_events(self) -> list[Event]:
        rows = self._run(f"MATCH (e:{self._label}) RETURN e ORDER BY e.occurred_at ASC")
        return [self._row_to_event(row["e"]) for row in rows]

    def all_edges(self) -> list[CausalEdge]:
        rows = self._run(f"MATCH (:{self._label})-[r:CAUSES]->(:{self._label}) RETURN r")
        return [self._row_to_edge(row["r"]) for row in rows]

    def clear(self) -> None:
        # Scoped to this store's label only — never a blanket wipe.
        self._run(f"MATCH (e:{self._label}) DETACH DELETE e")

    def clear_all(self) -> None:
        # Blanket wipe: every node + relationship in the database, regardless of label.
        self._run("MATCH (n) DETACH DELETE n")
