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


def _parse_batch(out: dict[str, Any], causes: list[Event]) -> list[dict[str, Any]]:
    """Map the model's judgments back onto every cause id; fill missing with neutral
    ("none" @ 0.0) so a partial answer degrades instead of crashing ingest."""
    by_id: dict[str, dict[str, Any]] = {}
    for j in out.get("judgments", []) or []:
        cause_id = str(j.get("cause_id", ""))
        if cause_id:
            by_id[cause_id] = {
                "cause_id": cause_id,
                "relation": j.get("relation", "none"),
                "confidence": float(j.get("confidence", 0.0) or 0.0),
                "justification": j.get("justification", ""),
            }
    return [
        by_id.get(
            c.id,
            {"cause_id": c.id, "relation": "none", "confidence": 0.0, "justification": ""},
        )
        for c in causes
    ]


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

    def judge_causality_batch(
        self, effect: Event, causes: list[Event]
    ) -> list[dict[str, Any]]:
        if not causes:
            return []
        lines = [
            "Effect:",
            f"  id={effect.id} occurred_at={effect.occurred_at.isoformat()}",
            f"  summary: {effect.summary}",
            f"  detail: {effect.detail}",
            f"  tags: {effect.tags}",
            "",
            "Candidate causes (each may or may not have contributed to the effect):",
        ]
        for c in causes:
            lines.append(
                f"  - cause_id={c.id} occurred_at={c.occurred_at.isoformat()}\n"
                f"    summary: {c.summary}\n"
                f"    detail: {c.detail}\n"
                f"    tags: {c.tags}"
            )
        out = self._tool_call(
            self._judgment_model,
            prompts.JUDGMENT_SYSTEM,
            "\n".join(lines),
            prompts.JUDGMENT_TOOL,
            max_tokens=1024,
        )
        return _parse_batch(out, causes)

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
