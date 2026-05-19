"""Skills export, skill diff, and knowledge gap analysis."""
from __future__ import annotations
import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from storage.brain import _read_brain
from core.logging import _utc_now_iso
from config import EXPORT_TOKEN

router = APIRouter()

@router.get("/api/skills_export")
def skills_export(token: str = ""):
    """Return brain state for SKILLS.md generation. Gated by EXPORT_TOKEN if set."""
    if EXPORT_TOKEN and token != EXPORT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing export token.")
    return _read_brain()


# ══════════════════════════════════════════════════════════════════════════════
# Skill diff — "what changed since your agent last loaded the skill"
# ══════════════════════════════════════════════════════════════════════════════
# This is the wedge feature. An agent (or human) passes ?since=<ISO_TIMESTAMP>;
# we return only the structural changes that happened after that point —
# decisions changed, owners changed, ADRs superseded, new facts, new code
# paths, etc. The point is: agents don't need to re-load the full skill on
# every call; they sync the delta. None of Cursor / Cody / Mem0 / Zep / Glean
# expose this shape today.

def _parse_iso(ts: Optional[str]) -> Optional[datetime.datetime]:
    if not ts:
        return None
    try:
        # Accept both Z and +00:00 suffixes
        clean = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        return datetime.datetime.fromisoformat(clean)
    except Exception:
        return None


def _after(unit_ts: Optional[str], since: Optional[datetime.datetime]) -> bool:
    if since is None:
        return True
    dt = _parse_iso(unit_ts)
    return dt is not None and dt > since


@router.get("/api/skill/diff")
def skill_diff(since: str = "", agent: str = ""):
    """Delta report since `since` (ISO timestamp). Optional `agent` filter for
    future per-agent scoping (currently a no-op — every diff sees all facts).

    Returns:
      {
        since, generatedAt,
        summary: { factsAdded, factsSuperseded, factsDisputed,
                   ownersChanged, decisionsChanged, codeSourcesAdded },
        factsAdded:        [unit, ...]   # new units since `since`
        factsSuperseded:   [{unit, supersededBy, validTo}]
        factsDisputed:     [unit, ...]   # units that *became* disputed in window
        ownersChanged:     [unit, ...]   # ownership-kind units since `since`
        decisionsChanged:  [unit, ...]   # decision-kind units since `since`
        adrsSuperseded:    [unit, ...]   # subset of factsSuperseded with code/adr evidence
        codeSourcesAdded:  [source, ...] # codebase ingests since `since`
        entityPathsTouched:{entity: [paths]}  # union over code sources in window
      }
    """
    since_dt = _parse_iso(since) if since else None
    brain = _read_brain()
    units = brain.get("units", [])

    facts_added = [u for u in units
                   if not u.get("stale")
                   and not u.get("supersededBy")
                   and _after(u.get("createdAt"), since_dt)]

    facts_superseded = [
        {
            "unit": u,
            "supersededBy": u.get("supersededBy"),
            "validTo": u.get("validTo"),
            "supersededAt": u.get("supersededAt"),
        }
        for u in units
        if u.get("supersededBy") and _after(u.get("supersededAt") or u.get("validTo"), since_dt)
    ]

    facts_disputed = [u for u in units
                      if u.get("disputed")
                      and _after(u.get("updatedAt") or u.get("createdAt"), since_dt)]

    owners_changed   = [u for u in facts_added if u.get("kind") == "ownership"]
    decisions_changed = [u for u in facts_added if u.get("kind") == "decision"]

    # An ADR supersession is a superseded fact whose evidence path looks like
    # an ADR (segments contain adr/adrs/rfc/decisions). Same heuristic as
    # _classify_file.
    def _is_adr_evidence(unit: dict) -> bool:
        for ev in unit.get("evidence", []) or []:
            path = (ev.get("path") or "").lower().replace("\\", "/")
            if any(s in path for s in ("/adr/", "/adrs/", "/rfc/", "/rfcs/",
                                       "/decisions/", "/decision-log/")):
                return True
        return False

    adrs_superseded = [s for s in facts_superseded if _is_adr_evidence(s["unit"])]

    # Code source deltas — codebases ingested in the window
    code_sources_added = [
        s for s in brain.get("sources", [])
        if s.get("kind") == "code" and _after(s.get("capturedAt"), since_dt)
    ]
    entity_paths_touched: dict[str, list[str]] = {}
    for s in code_sources_added:
        cb = s.get("codebase") or {}
        for ent, paths in (cb.get("entityPaths") or {}).items():
            entity_paths_touched.setdefault(ent, []).extend(paths)
    # de-dup
    for ent, paths in list(entity_paths_touched.items()):
        entity_paths_touched[ent] = sorted(set(paths))

    return {
        "since": since or None,
        "agent": agent or None,
        "generatedAt": _utc_now_iso(),
        "summary": {
            "factsAdded": len(facts_added),
            "factsSuperseded": len(facts_superseded),
            "factsDisputed": len(facts_disputed),
            "ownersChanged": len(owners_changed),
            "decisionsChanged": len(decisions_changed),
            "adrsSuperseded": len(adrs_superseded),
            "codeSourcesAdded": len(code_sources_added),
            "entityPathsTouched": len(entity_paths_touched),
        },
        "factsAdded": facts_added,
        "factsSuperseded": facts_superseded,
        "factsDisputed": facts_disputed,
        "ownersChanged": owners_changed,
        "decisionsChanged": decisions_changed,
        "adrsSuperseded": adrs_superseded,
        "codeSourcesAdded": code_sources_added,
        "entityPathsTouched": entity_paths_touched,
    }


@router.post("/api/analyze/gaps")
def analyze_gaps():
    """
    Find structural holes in the knowledge graph:
      - Systems / products / teams without a documented owner.
      - Entities mentioned but never described in any unit.
      - Gotchas without a sibling process/policy.
      - Disputed units waiting for resolution.
    Cheap, deterministic, no LLM call. Run on demand.
    """
    brain = _read_brain()
    units = [u for u in brain.get("units", []) if not u.get("stale") and not u.get("supersededBy")]
    entities = brain.get("entities", [])
    rels = brain.get("relationships", [])

    gaps = []

    # 1. Systems/products/teams with no owner
    OWNER_VERBS = {"owns", "manages", "governs"}
    owned_targets = {r["to"].lower() for r in rels if r["relation"].lower() in OWNER_VERBS}
    for e in entities:
        if e["kind"] in ("system", "product", "team") and e["name"].lower() not in owned_targets:
            gaps.append({
                "severity": "high",
                "kind": "missing_owner",
                "entity": e["name"],
                "message": f"No documented owner for {e['kind']} '{e['name']}'.",
            })

    # 2. Entities mentioned in units but never described as a subject
    subjects = {u["subject"].lower() for u in units if u.get("subject")}
    mentioned = {n.lower() for u in units for n in u.get("entities", [])}
    for name in mentioned - subjects:
        # Skip if the entity appears as an owner target (already covered)
        if name and name not in owned_targets and len(name) > 2:
            ent = next((e for e in entities if e["name"].lower() == name), None)
            if ent:
                gaps.append({
                    "severity": "medium",
                    "kind": "undescribed_entity",
                    "entity": ent["name"],
                    "message": f"'{ent['name']}' is mentioned but no unit describes it directly.",
                })

    # 3. Gotchas with no neighbouring process/policy
    by_subject: dict[str, set[str]] = {}
    for u in units:
        s = u.get("subject", "").lower()
        if s:
            by_subject.setdefault(s, set()).add(u.get("kind", ""))
    for u in units:
        if u.get("kind") == "gotcha":
            kinds = by_subject.get(u.get("subject", "").lower(), set())
            if not (kinds & {"process", "policy"}):
                gaps.append({
                    "severity": "low",
                    "kind": "orphan_gotcha",
                    "entity": u.get("subject", ""),
                    "message": f"Gotcha about '{u.get('subject')}' has no documented process or policy.",
                })

    # 4. Open disputes
    for u in units:
        if u.get("disputed"):
            gaps.append({
                "severity": "high",
                "kind": "open_dispute",
                "entity": u.get("subject", ""),
                "message": f"Disputed claim about '{u.get('subject')}': {u.get('statement')}",
                "unitId": u["id"],
                "conflictsWith": u.get("conflictsWith", []),
            })

    # Sort: high → medium → low
    sev_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: sev_order.get(g["severity"], 3))

    return {
        "gaps": gaps,
        "counts": {
            "high": sum(1 for g in gaps if g["severity"] == "high"),
            "medium": sum(1 for g in gaps if g["severity"] == "medium"),
            "low": sum(1 for g in gaps if g["severity"] == "low"),
            "total": len(gaps),
        },
    }


