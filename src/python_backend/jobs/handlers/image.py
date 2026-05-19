"""Job handler for image/VLM ingest."""
from __future__ import annotations
from storage.brain import _read_brain
from core.logging import _debug_event
from agents import ingest_agent, struct_agent

def _handler_ingest_image(job: Job, q: JobQueue) -> dict:
    p = job.payload
    image_data: bytes = p["data"]
    mime = p.get("mime") or "image/png"
    q.update_progress(job.id, step="describing image (VLM)", progress=0.15)
    description = ingest_agent.describe_image(image_data, mime, model_override=p.get("vlm_model"))
    if not (description or "").strip() or (description or "").startswith("[VLM description unavailable"):
        raise RuntimeError(description or "VLM did not return an image description.")
    q.update_progress(job.id, step="extracting facts", progress=0.55)
    extraction = ingest_agent.extract_from_text(
        f"image/{p['kind']}", p["title"], description,
        model_override=p.get("text_model") or p.get("vlm_model"),
    )
    used_fallback = False
    if not (extraction.get("units") or extraction.get("entities") or extraction.get("relationships")):
        extraction = _fallback_extract_from_document(f"image/{p['kind']}", p["title"], description)
        used_fallback = True
    q.update_progress(job.id, step="reconciling + storing", progress=0.85)
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id, "kind": p["kind"], "title": p["title"],
        "content": description, "url": p.get("url"), "capturedAt": now,
        "imageIngested": True, "imageFilename": p.get("filename"),
        "extractionMode": "fallback" if used_fallback else "model",
    }
    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=extraction.get("units", []),
        entities=extraction.get("entities", []),
        relationships=extraction.get("relationships", []),
        raw_chunks=[description],
    )
    return {
        "source_id": source_id, "vlm_description_chars": len(description),
        "units_extracted": len(extraction.get("units", [])),
        "entities_extracted": len(extraction.get("entities", [])),
        "relationships_extracted": len(extraction.get("relationships", [])),
        "fallback_extraction": used_fallback,
        **result,
    }


