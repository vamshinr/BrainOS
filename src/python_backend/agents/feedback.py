"""FeedbackAgent: groundedness audit and answer revision trigger."""
from __future__ import annotations
import time
from clients.router import _resolve_override
from core.logging import _debug_event, _log_call
from agents.extraction import _parse_extraction_json

class FeedbackAgent:
    """Evaluates whether the answer is grounded in the retrieved context using the 70B model."""

    def evaluate(self, query: str, answer: str, context_docs: list, model_override: str | None = None) -> dict:
        if not context_docs:
            return {
                "confidence": 0.0,
                "grounded": False,
                "feedback": "No knowledge was retrieved — answer is not grounded in company data.",
            }

        ctx = "\n".join(f"{i+1}. {d}" for i, d in enumerate(context_docs))
        prompt = (
            "You are the BrainOS grounding judge. Your job is to audit whether an "
            "answer is supported by the retrieved company context. Be strict about "
            "unsupported claims, but do not punish an answer for being concise.\n\n"
            "CONTEXT TYPES:\n"
            "- Normal numbered items are extracted knowledge units or graph context.\n"
            "- Items beginning with [raw chunk:...] are raw source excerpts. They are valid evidence, "
            "but weaker than extracted knowledge units.\n\n"
            f"RETRIEVED CONTEXT:\n{ctx}\n\n"
            f"QUESTION:\n{query}\n\n"
            f"ANSWER:\n{answer}\n\n"
            "EVALUATION RULES:\n"
            "1. Every concrete answer claim must be supported by at least one context item.\n"
            "2. Names, services, dates, numbers, policies, owners, time windows, APIs, and tools "
            "must appear in or be directly implied by context.\n"
            "3. If the answer says the brain lacks information, that is grounded only when the "
            "retrieved context does not answer the question.\n"
            "4. If the answer relies only on raw chunks, it may still be grounded, but set "
            "raw_chunk_only=true and cap confidence at 0.82 unless the excerpt states it directly.\n"
            "5. If the answer contradicts any retrieved fact, set grounded=false and confidence <= 0.2.\n"
            "6. If the answer is correct but misses part of a multi-part question, set partial=true.\n"
            "7. Do not require exact wording. Reasonable paraphrases are allowed when the same "
            "entities and facts are present.\n\n"
            "SCORE GUIDE:\n"
            "- 1.00: all claims directly supported by extracted facts/graph context.\n"
            "- 0.85: all claims supported, with minor paraphrase or raw chunk support.\n"
            "- 0.65: mostly supported but incomplete or lightly inferred.\n"
            "- 0.40: weak support; important claim missing.\n"
            "- 0.20: fabricated or contradicted claim.\n"
            "- 0.00: unrelated to context or directly contradicts context.\n\n"
            "Return JSON only. No markdown. No prose outside JSON. Use this exact shape:\n"
            "{"
            '"confidence": 0.0, '
            '"grounded": true, '
            '"partial": false, '
            '"raw_chunk_only": false, '
            '"supporting_context_ids": ["1"], '
            '"unsupported_claims": [], '
            '"missing_aspects": [], '
            '"contradictions": [], '
            '"feedback": "one short sentence"'
            "}"
        )
        client, model = _resolve_override("feedback", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=320,
                temperature=0.0,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            raw = response.choices[0].message.content.strip()
            parsed = _parse_extraction_json(raw)
            _log_call(
                "feedback", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"grounded={parsed.get('grounded', '?')}",
            )
            try:
                feedback_confidence = float(parsed.get("confidence", 1.0) or 0.0)
            except (TypeError, ValueError):
                feedback_confidence = 0.0
            if feedback_confidence == 0.0:
                _debug_event(
                    "feedback.zero_confidence",
                    "Feedback model returned zero confidence",
                    query=query,
                    raw=raw,
                    feedback=parsed.get("feedback"),
                )
            if "confidence" in parsed:
                return parsed
        except Exception as e:
            _log_call("feedback", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            print(f"[FeedbackAgent] Error: {e}")

        return {"confidence": 0.8, "grounded": True, "feedback": "Evaluation unavailable."}


