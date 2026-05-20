"""Chunking, extraction JSON parsing, and multi-chunk merge."""
from __future__ import annotations
import re
import json

def _parse_extraction_json(raw: str) -> dict:
    """Robustly extract JSON from LLM output that may include markdown fences."""
    raw = raw.strip()
    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    # Find outermost JSON object
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"entities": [], "units": [], "relationships": []}


# ══════════════════════════════════════════════════════════════════════════════
# Agents
# ══════════════════════════════════════════════════════════════════════════════

def _chunk_text(text: str, max_chars: int = 3500, overlap: int = 300) -> list[str]:
    """
    Split text into overlapping chunks that fit the model's context window.
    Each chunk is <= max_chars. Overlap carries context across boundaries.
    """
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        # Try to break at a paragraph or sentence boundary
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                pos = text.rfind(sep, start + max_chars // 2, end)
                if pos != -1:
                    end = pos + len(sep)
                    break
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def _merge_extractions(results: list[dict]) -> dict:
    """Combine entity + unit + relationship lists from multiple chunk extractions."""
    seen_entities: set[str] = set()
    seen_stmts: set[str] = set()
    seen_rels: set[tuple] = set()
    entities, units, relationships = [], [], []

    for r in results:
        for e in r.get("entities", []):
            key = e.get("name", "").lower()
            if key and key not in seen_entities:
                seen_entities.add(key)
                entities.append(e)
        for u in r.get("units", []):
            key = u.get("statement", "").lower()[:80]
            if key and key not in seen_stmts:
                seen_stmts.add(key)
                units.append(u)
        for rel in r.get("relationships", []):
            key = (rel.get("from", ""), rel.get("relation", ""), rel.get("to", ""))
            if all(key) and key not in seen_rels:
                seen_rels.add(key)
                relationships.append(rel)

    return {"entities": entities, "units": units, "relationships": relationships}


