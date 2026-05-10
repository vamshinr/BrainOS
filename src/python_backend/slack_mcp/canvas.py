from __future__ import annotations

from typing import Any


def build_canvas_markdown(title: str, markdown: str, department: str | None = None) -> str:
    heading = title.strip() or "BrainOS Knowledge Export"
    dept = f"\n_department: {department}_\n" if department else ""
    return f"# {heading}\n{dept}\n{markdown.strip()}\n"


def export_canvas(
    *,
    client: Any,
    title: str,
    markdown: str,
    department: str | None = None,
    canvas_id: str | None = None,
) -> dict[str, Any]:
    content = build_canvas_markdown(title, markdown, department)
    if canvas_id:
        result = client.update_canvas(canvas_id=canvas_id, markdown=content)
        action = "update_canvas"
    else:
        result = client.create_canvas(title=title, markdown=content)
        action = "create_canvas"
    return {"action": action, "title": title, "department": department, "result": result}

