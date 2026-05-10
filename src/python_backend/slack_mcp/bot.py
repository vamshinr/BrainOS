from __future__ import annotations

from typing import Any, Callable


def confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.65:
        return "medium"
    return "low"


def format_slack_answer(answer: str, feedback: dict[str, Any], used: list[str]) -> str:
    try:
        confidence = float(feedback.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    grounded = bool(feedback.get("grounded"))
    if confidence < 0.45 or not grounded:
        return "BrainOS does not have enough grounded evidence to answer this from the current knowledge base."
    source_line = ", ".join(used[:4]) if used else "retrieved BrainOS evidence"
    return (
        f"{answer.strip()}\n\n"
        f"Confidence: {confidence_label(confidence)} | Grounded: {'yes' if grounded else 'partial'}\n"
        f"Sources: {source_line}"
    )


def answer_for_slack(
    question: str,
    *,
    exec_agent: Any,
    feedback_agent: Any,
    is_sensitive: Callable[[str], str | None],
    debug_event: Callable[..., None],
    model: str | None = None,
) -> dict[str, Any]:
    blocked = is_sensitive(question)
    if blocked:
        answer = f"This brain is configured to refuse questions touching '{blocked}'."
        feedback = {"confidence": 1.0, "grounded": True, "feedback": "Blocked by policy."}
        return {
            "answer": answer,
            "slack_text": answer,
            "used": [],
            "retrieval_mode": None,
            "retrieval_debug": None,
            "feedback": feedback,
            "blocked_topic": blocked,
        }

    exec_result = exec_agent.execute(question, model_override=model)
    verification_context = exec_result.get("verification_context") or exec_result.get("retrieved_docs", [])
    draft_answer = exec_result.get("answer", "")
    answer_revised = False
    feedback = feedback_agent.evaluate(
        query=question,
        answer=draft_answer,
        context_docs=verification_context,
        model_override=model,
    )
    try:
        confidence = float(feedback.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    if (
        feedback.get("grounded") is False
        or confidence < 0.72
        or feedback.get("unsupported_claims")
        or feedback.get("contradictions")
    ) and verification_context:
        debug_event(
            "slack.ask.revise.start",
            "Verifier requested Slack answer revision",
            confidence=confidence,
            grounded=feedback.get("grounded"),
        )
        revised = exec_agent.revise_answer(
            query=question,
            draft_answer=draft_answer,
            context_docs=verification_context,
            verification=feedback,
            model_override=model,
        )
        if revised and revised != draft_answer:
            answer_revised = True
            exec_result["answer"] = revised
            revised_feedback = feedback_agent.evaluate(
                query=question,
                answer=revised,
                context_docs=verification_context,
                model_override=model,
            )
            revised_feedback["pre_revision_feedback"] = feedback
            feedback = revised_feedback

    used = exec_result.get("retrieved_ids", [])
    return {
        "answer": exec_result.get("answer", ""),
        "draft_answer": draft_answer if answer_revised else None,
        "answer_revised": answer_revised,
        "slack_text": format_slack_answer(exec_result.get("answer", ""), feedback, used),
        "used": used,
        "retrieved_texts": exec_result.get("retrieved_docs", []),
        "latency_ms": exec_result.get("latency_ms"),
        "retrieval_mode": exec_result.get("retrieval_mode"),
        "retrieval_debug": exec_result.get("retrieval_debug"),
        "feedback": feedback,
    }

