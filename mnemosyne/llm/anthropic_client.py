"""Anthropic-backed LLM client: Haiku for both event extraction and causal judgment.

Two separate, structured (tool-forced) calls. The API key is read from config (env);
never hardcoded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import anthropic

from ..models import Event
from . import prompts


class AnthropicLLM:
    def __init__(
        self,
        api_key: str,
        *,
        extraction_model: str,
        judgment_model: str,
        extraction_max_tokens: int = 4096,
    ) -> None:
        if not api_key:
            raise ValueError("AnthropicLLM requires an API key (ANTHROPIC_API_KEY / CLAUDE_API_KEY)")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._extraction_model = extraction_model
        self._judgment_model = judgment_model
        self._extraction_max_tokens = extraction_max_tokens

    def _tool_call(
        self, model: str, system: str, user: str, tool: dict, max_tokens: int = 2048
    ) -> dict[str, Any]:
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        for block in resp.content:
            if block.type == "tool_use":
                return dict(block.input)
        raise ValueError(f"LLM returned no tool_use block for tool {tool['name']}")

    def extract_events(
        self, text: str, reference_time: datetime, context: str = ""
    ) -> list[dict[str, Any]]:
        header = f"Reference time (treat as 'now'): {reference_time.isoformat()}"
        if context:
            user = (
                f"{header}\n\n"
                "=== CONTEXT FROM PRECEDING TEXT (for reference only — do NOT extract events "
                f"from this section) ===\n{context}\n\n"
                f"=== EXTRACT EVENTS FROM THIS SECTION ONLY ===\n{text}\n---"
            )
        else:
            user = f"{header}\n\nText to extract events from:\n---\n{text}\n---"
        out = self._tool_call(
            self._extraction_model,
            prompts.EXTRACTION_SYSTEM,
            user,
            prompts.EXTRACTION_TOOL,
            max_tokens=self._extraction_max_tokens,
        )
        events = out.get("events", [])
        return events if isinstance(events, list) else []

    def judge_causality(self, cause: Event, effect: Event) -> dict[str, Any]:
        user = (
            "Candidate cause (A):\n"
            f"  id={cause.id} occurred_at={cause.occurred_at.isoformat()}\n"
            f"  summary: {cause.summary}\n  detail: {cause.detail}\n  tags: {cause.tags}\n\n"
            "Candidate effect (B):\n"
            f"  id={effect.id} occurred_at={effect.occurred_at.isoformat()}\n"
            f"  summary: {effect.summary}\n  detail: {effect.detail}\n  tags: {effect.tags}\n\n"
            "Did event A causally contribute to event B?"
        )
        out = self._tool_call(
            self._judgment_model, prompts.JUDGMENT_SYSTEM, user, prompts.JUDGMENT_TOOL, max_tokens=512
        )
        return {
            "relation": out.get("relation", "none"),
            "confidence": float(out.get("confidence", 0.0) or 0.0),
            "justification": out.get("justification", ""),
        }

    def synthesize(self, query: str, ordered_chain: list[dict[str, Any]]) -> str:
        lines = []
        for entry in ordered_chain:
            ev = entry["event"]
            rel = entry.get("incoming_relation")
            conf = entry.get("confidence")
            edge = f" (incoming: {rel} @ {conf:.2f})" if rel else " (root cause)"
            lines.append(f"[{ev['id']}] {ev['occurred_at']} — {ev['summary']}{edge}")
        user = f"Question: {query}\n\nOrdered causal chain:\n" + "\n".join(lines)
        resp = self._client.messages.create(
            model=self._judgment_model,
            max_tokens=512,
            system=prompts.SYNTHESIS_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()
