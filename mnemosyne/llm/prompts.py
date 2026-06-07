"""Prompts and structured-output tool schemas for the two LLM calls.

Extraction and causal judgment are deliberately kept as *separate* LLM calls with
forced structured (JSON) outputs, validated downstream. Fail loudly on malformed
output rather than guessing.
"""

EXTRACTION_SYSTEM = """You extract discrete, timestamped EVENTS from raw text \
(a chat turn, a log block, or a document).

Rules:
- An event is something that HAPPENED at a point in time — a state change, an action, \
an observation. Not a static fact, not an opinion.
- Resolve every relative time ("this afternoon", "6 minutes later", "3 weeks ago") to an \
absolute ISO-8601 timestamp WITH timezone, using the provided reference time as "now".
- If the text contains no datable events, return an empty list.
- summary: one concise line. detail: the supporting full text. tags: the key \
entities/topics (systems, services, components, people) as short lowercase strings.
Return your answer ONLY via the emit_events tool."""

EXTRACTION_TOOL = {
    "name": "emit_events",
    "description": "Emit the discrete timestamped events found in the text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string", "description": "one concise line"},
                        "detail": {"type": "string", "description": "supporting full text"},
                        "occurred_at": {
                            "type": "string",
                            "description": "absolute ISO-8601 timestamp with timezone",
                        },
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["summary", "occurred_at", "tags"],
                },
            }
        },
        "required": ["events"],
    },
}

JUDGMENT_SYSTEM = """You judge whether one event causally CONTRIBUTED to another.

This is approximate causality (temporal precedence + association + your judgment), not \
proof. Be conservative: if B would plausibly have happened regardless of A, say the \
relation is "none" with low confidence.

relation:
- "caused"    — A directly produced B
- "triggered" — A set B in motion
- "led_to"    — A contributed to B through a chain
- "enabled"   — A made B possible but was not sufficient alone
- "none"      — no causal contribution

confidence: 0..1. justification: ONE sentence. Answer ONLY via the emit_judgment tool."""

JUDGMENT_TOOL = {
    "name": "emit_judgment",
    "description": "Emit the causal judgment for the candidate pair.",
    "input_schema": {
        "type": "object",
        "properties": {
            "relation": {
                "type": "string",
                "enum": ["caused", "triggered", "led_to", "enabled", "none"],
            },
            "confidence": {"type": "number"},
            "justification": {"type": "string"},
        },
        "required": ["relation", "confidence", "justification"],
    },
}

SYNTHESIS_SYSTEM = """You explain WHY something happened, given an ordered, time-stamped \
causal chain of events. Write a tight narrative (2-5 sentences) that follows the chain \
from root cause to outcome. Cite event ids in [brackets] and include timestamps. Use \
ONLY the events provided — never invent steps. If the chain is a single event, say the \
cause is not yet established."""
