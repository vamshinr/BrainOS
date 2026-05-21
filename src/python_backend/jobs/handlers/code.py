"""Query-time code-map context.

Surfaces entity↔path links, symbol locations, and module summaries from
codebases that were ingested while the code/repo upload feature was enabled.
Read-only — the code-ingest pipeline (zip walk, outlines, call/import graphs)
has been removed; this only reads `codebase` blocks already in brain.json.
"""
from __future__ import annotations
import re


def _code_context_for_query(query: str, brain: dict, limit: int = 6) -> list[str]:
    q = (query or "").lower()
    if not q:
        return []
    code_sources = [s for s in brain.get("sources", [])
                     if s.get("kind") == "code" and s.get("codebase")]
    if not code_sources:
        return []

    lines: list[str] = []
    seen: set[str] = set()

    def push(line: str):
        if line and line not in seen and len(lines) < limit:
            seen.add(line)
            lines.append(line)

    q_tokens = {t for t in re.split(r"[^a-z0-9]+", q) if len(t) > 2}

    for src in code_sources:
        cb = src["codebase"]

        # Entity ↔ path matches
        for ent, paths in (cb.get("entityPaths") or {}).items():
            if ent.lower() in q or any(t in q for t in re.split(r"[^a-z0-9]+", ent.lower()) if len(t) > 2):
                shown = ", ".join(paths[:4])
                more = f" (+{len(paths) - 4} more)" if len(paths) > 4 else ""
                push(f"[code] entity '{ent}' is referenced at: {shown}{more}")

        # Symbol index matches
        sidx = cb.get("symbolIndex") or {}
        for name, occurrences in sidx.items():
            if name.lower() in q_tokens or any(name.lower() in t for t in q_tokens):
                first = occurrences[0]
                more = f" (+{len(occurrences) - 1} more)" if len(occurrences) > 1 else ""
                push(f"[code] symbol '{name}' ({first.get('kind', '?')}) defined at {first['path']}:{first.get('line', 0)}{more}")

        # Module summaries — match dir name in query
        for mod in cb.get("moduleSummaries") or []:
            if mod["dir"].lower() in q_tokens:
                push(f"[code] module '{mod['dir']}/' — {mod['summary']}")

    return lines
