"""POST /api/ask — hybrid retrieval and grounded answer generation."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.security import _is_sensitive
from core.logging import _debug_event
from agents import exec_agent, feedback_agent

router = APIRouter()

class QueryRequest(BaseModel):
    query: str
    model: Optional[str] = None  # per-request override; falls back to routed default
    as_of: Optional[str] = None  # ISO date string for temporal time-travel queries

@router.post("/api/ask")
def ask_brainos(req: QueryRequest):
    blocked = _is_sensitive(req.query)
    if blocked:
        return {
            "query": req.query,
            "answer": (
                f"This brain is configured to refuse questions touching '{blocked}'. "
                "Contact a brain administrator if you need this information."
            ),
            "used": [],
            "retrieved_texts": [],
            "latency_ms": 0,
            "feedback": {"confidence": 1.0, "grounded": True, "feedback": "Blocked by policy."},
            "blocked_topic": blocked,
        }

    effective_query = req.query
    if req.as_of:
        effective_query = f"As of {req.as_of}: {req.query}"

    try:
        exec_result = exec_agent.execute(effective_query, model_override=req.model)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM unavailable: {e}")

    verification_context = exec_result.get("verification_context") or exec_result["retrieved_docs"]
    answer_revised = False
    draft_answer = exec_result["answer"]
    try:
        feedback = feedback_agent.evaluate(
            query=req.query,
            answer=draft_answer,
            context_docs=verification_context,
            model_override=req.model,
        )
    except Exception:
        feedback = {"confidence": 0.0, "grounded": False, "feedback": "Evaluation unavailable."}

    try:
        confidence = float(feedback.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    unsupported = feedback.get("unsupported_claims") or []
    contradictions = feedback.get("contradictions") or []
    needs_revision = (
        feedback.get("grounded") is False
        or confidence < 0.72
        or bool(unsupported)
        or bool(contradictions)
    )

    if needs_revision and verification_context:
        _debug_event(
            "answer.revise.start",
            "Verifier requested evidence-constrained answer revision",
            confidence=confidence,
            grounded=feedback.get("grounded"),
            unsupported=len(unsupported),
            contradictions=len(contradictions),
        )
        revised_answer = exec_agent.revise_answer(
            query=req.query,
            draft_answer=draft_answer,
            context_docs=verification_context,
            verification=feedback,
            model_override=req.model,
        )
        if revised_answer and revised_answer != draft_answer:
            exec_result["answer"] = revised_answer
            answer_revised = True
            try:
                revised_feedback = feedback_agent.evaluate(
                    query=req.query,
                    answer=revised_answer,
                    context_docs=verification_context,
                    model_override=req.model,
                )
                revised_feedback["pre_revision_feedback"] = feedback
                feedback = revised_feedback
            except Exception:
                feedback["revision_note"] = "Answer was revised, but second-pass evaluation failed."

    return {
        "query": req.query,
        "answer": exec_result["answer"],
        "draft_answer": draft_answer if answer_revised else None,
        "answer_revised": answer_revised,
        "used": exec_result["retrieved_ids"],
        "retrieved_texts": exec_result["retrieved_docs"],  # actual sentences sent to the model
        "latency_ms": exec_result["latency_ms"],
        "retrieval_mode": exec_result.get("retrieval_mode"),
        "retrieval_debug": exec_result.get("retrieval_debug"),
        "feedback": feedback,
    }


