"""Chunking, extraction JSON parsing, and multi-chunk merge."""
from __future__ import annotations
import re
import json

def _parse_extraction_json(raw: str) -> dict:
    """Robustly extract JSON from LLM output that may include markdown fences."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned unparseable JSON: {e} — raw={raw[:200]!r}") from e


_VALID_UNIT_KINDS = {"fact", "process", "decision", "ownership", "definition", "policy", "gotcha"}
_VALID_DEPARTMENTS = {
    "engineering", "product", "legal", "finance", "hr",
    "sales", "marketing", "operations", "security", "customer_success", "general",
}
_VALID_TEMPORAL_STATUSES = {"current", "future", "expired", "historical", "unknown"}

# Derived from department — LLM no longer emits sector, we compute it deterministically.
_DEPT_TO_SECTOR: dict[str, str] = {
    "engineering": "Engineering",
    "product": "Product",
    "legal": "Legal",
    "finance": "Finance",
    "hr": "HR",
    "operations": "Supply Chain",
    "security": "Engineering",
    "customer_success": "General",
    "sales": "General",
    "marketing": "General",
    "general": "General",
}


def _validate_extraction(data: dict) -> dict:
    """
    Validate and coerce the raw extraction dict into the expected schema.
    Drops malformed entries rather than letting garbage propagate into the brain.
    Returns a clean dict with entities/units/relationships guaranteed present.
    """
    entities = []
    for e in data.get("entities") or []:
        if not isinstance(e, dict):
            continue
        name = (e.get("name") or "").strip()
        if not name:
            continue
        entities.append({
            "name": name,
            "kind": e.get("kind") or "concept",
            "aliases": [a for a in (e.get("aliases") or []) if isinstance(a, str) and a.strip()],
            "description": (e.get("description") or "").strip(),
            "evidence_quote": (e.get("evidence_quote") or "").strip(),
        })

    units = []
    for u in data.get("units") or []:
        if not isinstance(u, dict):
            continue
        statement = (u.get("statement") or "").strip()
        if not statement:
            continue
        kind = u.get("kind") or "fact"
        if kind not in _VALID_UNIT_KINDS:
            kind = "fact"
        dept = (u.get("department") or "general").strip().lower()
        if dept not in _VALID_DEPARTMENTS:
            dept = "general"
        try:
            conf = float(u["confidence"]) if u.get("confidence") is not None else 0.7
        except (TypeError, ValueError):
            conf = 0.7
        ts = u.get("temporal_status") or "unknown"
        if ts not in _VALID_TEMPORAL_STATUSES:
            ts = "unknown"
        units.append({
            "kind": kind,
            "department": dept,
            "sector": _DEPT_TO_SECTOR.get(dept, "General"),  # derived, not from LLM
            "subject": (u.get("subject") or "").strip(),
            "statement": statement,
            "entities": [e for e in (u.get("entities") or []) if isinstance(e, str) and e.strip()],
            "evidence_quote": (u.get("evidence_quote") or "").strip(),
            "confidence": round(max(0.0, min(1.0, conf)), 4),
            "temporal_status": ts,
            "valid_from": u.get("valid_from") or "",
            "valid_to": u.get("valid_to") or "",
            "effective_date": u.get("effective_date") or "",
            "observed_at": u.get("observed_at") or "",
        })

    relationships = []
    for r in data.get("relationships") or []:
        if not isinstance(r, dict):
            continue
        frm = (r.get("from") or "").strip()
        to = (r.get("to") or "").strip()
        relation = (r.get("relation") or "").strip()
        if not (frm and to and relation):
            continue
        try:
            conf = float(r["confidence"]) if r.get("confidence") is not None else 0.7
        except (TypeError, ValueError):
            conf = 0.7
        ts = r.get("temporal_status") or "unknown"
        if ts not in _VALID_TEMPORAL_STATUSES:
            ts = "unknown"
        relationships.append({
            "from": frm,
            "relation": relation,
            "to": to,
            "evidence_quote": (r.get("evidence_quote") or "").strip(),
            "confidence": round(max(0.0, min(1.0, conf)), 4),
            "temporal_status": ts,
        })

    return {"entities": entities, "units": units, "relationships": relationships}


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


