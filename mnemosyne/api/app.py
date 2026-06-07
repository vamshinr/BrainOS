"""FastAPI surface for Mnemosyne.

  POST /ingest        text in -> events extracted, edges inferred, stored
  POST /retrieve      query in -> causal chain or associative chunks out
  GET  /graph         dump nodes + edges (visualization / debugging)
  GET  /event/{id}    inspect a single event + its edges
  POST /edge          operator-asserted edge (enforces the causality invariant)
  GET  /health        liveness
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from .. import __version__
from ..models import CausalityViolation
from ..service import MnemosyneService
from . import deps
from .schemas import IngestRequest, ManualEdgeRequest, RetrieveRequest

app = FastAPI(title="Mnemosyne — Causal Memory Engine", version=__version__)

from .jobs_routes import router as jobs_router  # noqa: E402

app.include_router(jobs_router)


def _service() -> MnemosyneService:
    try:
        return deps.get_service()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"backend unavailable: {exc}")


@app.post("/ingest")
def ingest(req: IngestRequest, svc: MnemosyneService = Depends(_service)):
    try:
        return svc.ingest(req.text, source_id=req.source_id, reference_time=req.reference_time)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/retrieve")
def retrieve(req: RetrieveRequest, svc: MnemosyneService = Depends(_service)):
    return svc.retrieve(req.query, k=req.k, mode=req.mode)


@app.get("/graph")
def graph(svc: MnemosyneService = Depends(_service)):
    return svc.graph_dump()


@app.get("/event/{event_id}")
def event(event_id: str, svc: MnemosyneService = Depends(_service)):
    result = svc.get_event(event_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"event {event_id} not found")
    return result


@app.post("/edge")
def edge(req: ManualEdgeRequest, svc: MnemosyneService = Depends(_service)):
    try:
        return svc.add_manual_edge(
            req.cause_id,
            req.effect_id,
            relation=req.relation,
            confidence=req.confidence,
            evidence=req.evidence,
        )
    except CausalityViolation as exc:
        # Causes must precede effects — a hard invariant, not a soft check.
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/reset")
def reset(svc: MnemosyneService = Depends(_service)):
    """Clear all events + edges from every store (destructive)."""
    return svc.reset()


@app.get("/health")
def health():
    try:
        return deps.get_service().health()
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "error": str(exc)}
