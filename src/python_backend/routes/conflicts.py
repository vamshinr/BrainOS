"""Conflict resolution endpoints."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from storage.brain import _read_brain, _write_brain
from storage.chroma import collection
from core.logging import _utc_now_iso

router = APIRouter()

# ══════════════════════════════════════════════════════════════════════════════
# Conflicts resolution
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/conflicts")
def get_conflicts():
    """Return all disputed unit pairs ready for human resolution."""
    brain = _read_brain()
    units_by_id = {u["id"]: u for u in brain.get("units", [])}

    seen_pairs: set[frozenset] = set()
    pairs = []

    for unit in brain.get("units", []):
        if not unit.get("disputed") or unit.get("stale") or unit.get("supersededBy"):
            continue
        for conflict_id in unit.get("conflictsWith", []):
            pair_key = frozenset([unit["id"], conflict_id])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            other = units_by_id.get(conflict_id)
            if not other:
                continue
            pairs.append({"unit_a": unit, "unit_b": other})

    return {"conflicts": pairs, "total": len(pairs)}


class ResolveConflictRequest(BaseModel):
    winner_id: str
    loser_id: str


@router.post("/api/conflicts/resolve")
def resolve_conflict(req: ResolveConflictRequest):
    """Mark the loser as superseded by the winner and clear disputed flags."""
    brain = _read_brain()
    units_by_id = {u["id"]: u for u in brain.get("units", [])}

    winner = units_by_id.get(req.winner_id)
    loser = units_by_id.get(req.loser_id)

    if not winner:
        raise HTTPException(status_code=404, detail=f"Winner unit {req.winner_id} not found")
    if not loser:
        raise HTTPException(status_code=404, detail=f"Loser unit {req.loser_id} not found")

    now = _utc_now_iso()

    # Mark loser as superseded
    loser["stale"] = True
    loser["supersededBy"] = req.winner_id
    loser["supersededAt"] = now
    if not loser.get("validTo"):
        loser["validTo"] = now[:10]
    loser["temporalStatus"] = "historical"
    loser["disputed"] = False
    loser["conflictsWith"] = [c for c in loser.get("conflictsWith", []) if c != req.winner_id]

    # Clear disputed from winner
    winner["disputed"] = False
    winner["conflictsWith"] = [c for c in winner.get("conflictsWith", []) if c != req.loser_id]
    if not winner.get("temporalStatus") or winner.get("temporalStatus") == "unknown":
        winner["temporalStatus"] = "current"

    _write_brain(brain)

    # Remove the loser from ChromaDB so it no longer pollutes retrieval
    try:
        collection.delete(ids=[req.loser_id])
    except Exception:
        pass

    return {
        "ok": True,
        "winner_id": req.winner_id,
        "loser_id": req.loser_id,
        "resolved_at": now,
    }


