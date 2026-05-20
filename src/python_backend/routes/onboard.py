"""Onboarding co-pilot: generate personalized day-one guides."""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from storage.brain import _read_brain
from clients.router import router as model_router

router = APIRouter()

# ══════════════════════════════════════════════════════════════════════════════
# Onboarding co-pilot
# ══════════════════════════════════════════════════════════════════════════════

class OnboardRequest(BaseModel):
    department: str = "general"
    role: str = ""


@router.post("/api/onboard")
def generate_onboard_doc(req: OnboardRequest):
    """Generate a personalized onboarding guide for a given department/role."""
    brain = _read_brain()
    dept = (req.department or "general").lower().strip()
    role = (req.role or "").strip()

    active = [
        u for u in brain.get("units", [])
        if not u.get("stale") and not u.get("supersededBy")
    ]

    # Filter by department when not "general"
    if dept != "general":
        dept_units = [u for u in active if (u.get("department") or "").lower() == dept]
        # Fall back to all units if the department has too few
        filtered = dept_units if len(dept_units) >= 3 else active
    else:
        filtered = active

    # Group by kind
    by_kind: dict[str, list] = {}
    for u in filtered:
        by_kind.setdefault(u.get("kind", "fact"), []).append(u)

    def _fmt(units: list, limit: int = 20) -> str:
        return "\n".join(
            f"- [{u.get('subject', '?')}] {u.get('statement', '')}"
            for u in units[:limit]
        )

    sections = {
        "ownership": _fmt(by_kind.get("ownership", [])),
        "process": _fmt(by_kind.get("process", [])),
        "gotcha": _fmt(by_kind.get("gotcha", [])),
        "policy": _fmt(by_kind.get("policy", [])),
        "decision": _fmt(by_kind.get("decision", [])),
        "fact": _fmt(by_kind.get("fact", []), limit=10),
    }

    dept_label = dept.title() if dept != "general" else "the company"
    role_clause = f" as a {role}" if role else ""
    unit_count = len(filtered)

    # Build onboarding doc with LLM if available, else deterministic fallback
    system_prompt = (
        "You are BrainOS, a company knowledge assistant. Your job is to generate a concise, "
        "practical onboarding guide for a new team member. Use only the facts provided. "
        "Be direct and specific. Format the output in clean Markdown with sections and bullet points. "
        "Do not invent information not present in the provided facts."
    )

    user_content = f"""Generate an onboarding guide for someone joining the {dept_label} team{role_clause}.

Use the following knowledge extracted from the company brain:

OWNERSHIP:
{sections['ownership'] or '(none documented)'}

KEY PROCESSES:
{sections['process'] or '(none documented)'}

GOTCHAS & PITFALLS (read carefully):
{sections['gotcha'] or '(none documented)'}

POLICIES:
{sections['policy'] or '(none documented)'}

KEY DECISIONS:
{sections['decision'] or '(none documented)'}

KEY FACTS:
{sections['fact'] or '(none documented)'}

Write the guide with these sections:
1. Welcome & Team Overview
2. Who's Who (ownership map)
3. Key Processes
4. Gotchas & Pitfalls (always include this section even if brief)
5. Policies to Know
6. Key Decisions & Context
7. First Week Checklist (5-7 actionable bullets)

Keep it practical, not generic."""

    try:
        client, model = model_router.get("execute")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        doc = response.choices[0].message.content.strip()
    except Exception as e:
        lines = [f"# Onboarding Guide: {dept_label.title()} Team{role_clause}\n"]
        if sections["ownership"]:
            lines += ["\n## Who's Who\n", sections["ownership"]]
        if sections["process"]:
            lines += ["\n## Key Processes\n", sections["process"]]
        if sections["gotcha"]:
            lines += ["\n## Gotchas & Pitfalls\n", sections["gotcha"]]
        if sections["policy"]:
            lines += ["\n## Policies\n", sections["policy"]]
        if sections["decision"]:
            lines += ["\n## Key Decisions\n", sections["decision"]]
        lines.append(f"\n\n---\n*Generated from {unit_count} knowledge units. LLM unavailable: {e}*")
        doc = "\n".join(lines)

    return {
        "doc": doc,
        "department": dept,
        "role": role,
        "unit_count": unit_count,
        "sections": {k: len(v) for k, v in by_kind.items()},
    }

