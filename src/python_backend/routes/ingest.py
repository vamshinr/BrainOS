"""Ingest routes: text, file, image, code, and mock."""
from __future__ import annotations
import uuid
import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from storage.brain import _read_brain
from core.logging import _debug_event, _utc_now_iso
from jobs import job_queue
from jobs.handlers.file import _extract_file_text
from jobs.handlers.code import _code_context_for_query

router = APIRouter()

class IngestRequest(BaseModel):
    kind: str
    title: Optional[str] = None
    content: str
    url: Optional[str] = None
    model: Optional[str] = None  # per-request override for the extraction call

def _infer_unit_kind(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("owner", "owned by", "owns ", "responsible for", "maintained by", "led by")):
        return "ownership"
    if any(word in lowered for word in ("must", "required", "requires", "always", "never", "policy", "approval", "approvals")):
        return "policy"
    if any(word in lowered for word in ("step ", "deploy", "run ", "create ", "merge ", "tag ", "restart", "escalate")):
        return "process"
    if any(word in lowered for word in ("decided", "decision", "chose", "selected", "standardized on")):
        return "decision"
    if any(word in lowered for word in ("means", "defined as", "refers to", " is a ", " is an ")):
        return "definition"
    if any(word in lowered for word in ("gotcha", "caveat", "avoid", "fails", "failure", "silently", "unless", "except")):
        return "gotcha"
    return "fact"


def _infer_department(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("api", "service", "deploy", "infra", "database", "pr ", "repo", "on-call", "incident")):
        return "engineering"
    if any(word in lowered for word in ("security", "soc2", "access", "secret", "vulnerability", "audit")):
        return "security"
    if any(word in lowered for word in ("contract", "legal", "nda", "privacy", "compliance", "regulatory")):
        return "legal"
    if any(word in lowered for word in ("invoice", "billing", "budget", "payment", "pricing", "revenue")):
        return "finance"
    if any(word in lowered for word in ("hiring", "pto", "benefits", "performance", "manager", "employee")):
        return "hr"
    if any(word in lowered for word in ("customer", "roadmap", "feature", "release", "ux", "backlog")):
        return "product"
    if any(word in lowered for word in ("sales", "pipeline", "quota", "account", "renewal")):
        return "sales"
    if any(word in lowered for word in ("campaign", "brand", "launch", "content", "comms")):
        return "marketing"
    if any(word in lowered for word in ("vendor", "inventory", "shipping", "warehouse", "procurement")):
        return "operations"
    return "general"


def _infer_sector(department: str) -> str:
    return {
        "engineering": "Engineering",
        "product": "Product",
        "legal": "Legal",
        "finance": "Finance",
        "hr": "HR",
        "operations": "Supply Chain",
    }.get(department, "General")


def _extract_candidate_entities(text: str) -> list[dict]:
    candidates: list[str] = []
    patterns = [
        r"\b[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)+(?:\s+[A-Z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)*)*\b",
        r"\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3}\b",
        r"\b[A-Za-z][A-Za-z0-9_-]*(?:API|DB|SDK|CLI|SVC|svc)\b",
        r"\b[A-Za-z][A-Za-z0-9_-]*(?:\s+(?:team|service|api|database|platform|policy|runbook))\b",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text, flags=re.IGNORECASE if "team|service" in pattern else 0))

    seen: set[str] = set()
    entities: list[dict] = []
    stopwords = {"The", "This", "That", "When", "After", "Before", "All", "Every", "Each"}
    for raw in candidates:
        name = re.sub(r"\s+", " ", raw).strip(" .,:;()[]")
        if not name or name.split()[0] in stopwords:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        lowered = key
        if any(word in lowered for word in ("team", "group")):
            kind = "team"
        elif any(word in lowered for word in ("api", "service", "svc", "db", "database", "platform")):
            kind = "system"
        elif any(word in lowered for word in ("policy", "runbook", "process")):
            kind = "process"
        elif len(name.split()) >= 2 and all(part[:1].isupper() for part in name.split()[:2]):
            kind = "person"
        else:
            kind = "concept"
        entities.append({"name": name, "kind": kind, "aliases": []})
        if len(entities) >= 40:
            break
    return entities


@router.post("/api/ingest")
def ingest_text(req: IngestRequest):
    """Enqueue a text ingest job. Returns immediately with a job_id; subscribe
    to /api/jobs/stream for progress."""
    title = req.title or (req.content.strip().splitlines()[0][:80] if req.content.strip() else f"Untitled {req.kind}")
    _debug_event(
        "ingest.text.enqueue", "Queued text ingestion job",
        title=title, kind=req.kind, url=req.url, model=req.model, chars=len(req.content),
    )
    job = job_queue.submit(
        kind="ingest_text", title=title, handler=_handler_ingest_text,
        payload={"kind": req.kind, "title": title, "content": req.content,
                 "url": req.url, "model": req.model},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


_MAX_EXTRACTION_CHARS = 12_000  # ~3k tokens; keeps prompt well inside 70B context window


@router.post("/api/ingest_file")
async def ingest_file(
    title: Optional[str] = Form(None),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Enqueue a file ingest job. We read the bytes now (so the UploadFile
    handle stays valid) then return immediately with a job_id."""
    data = await file.read()
    filename = file.filename or "upload"
    if not title:
        title = filename.rsplit(".", 1)[0] or filename
    _debug_event(
        "ingest.file.enqueue", "Queued file ingestion job",
        title=title, kind=kind, url=url, model=model,
        filename=file.filename, content_type=file.content_type, bytes=len(data),
    )
    job = job_queue.submit(
        kind="ingest_file", title=title, handler=_handler_ingest_file,
        payload={"kind": kind, "title": title, "url": url, "model": model,
                 "filename": filename, "data": data},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


@router.post("/api/ingest_image")
async def ingest_image(
    title: Optional[str] = Form(None),
    kind: str = Form("doc"),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),       # VLM model override
    text_model: Optional[str] = Form(None),  # extraction model override
    file: UploadFile = File(...),
):
    """Enqueue an image ingest job (VLM → extraction → store)."""
    image_data = await file.read()
    mime = file.content_type or "image/png"
    if not title:
        fname = file.filename or "image"
        title = fname.rsplit(".", 1)[0] or fname
    _debug_event(
        "ingest.image.enqueue", "Queued image ingestion job",
        title=title, kind=kind, url=url, vlm_model=model, text_model=text_model,
        filename=file.filename, content_type=file.content_type, bytes=len(image_data),
    )
    job = job_queue.submit(
        kind="ingest_image", title=title, handler=_handler_ingest_image,
        payload={"kind": kind, "title": title, "url": url, "filename": file.filename,
                 "data": image_data, "mime": mime,
                 "vlm_model": model, "text_model": text_model},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


@router.post("/api/ingest_code")
async def ingest_code(
    title: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    model: Optional[str] = Form(None),       # extraction model override
    file: UploadFile = File(...),
):
    """Enqueue a code-ingest job. Accepts:
       • a .zip of a repo (preferred) — full file-tree map + CODEOWNERS +
         ADR/RFC/README rationale extraction
       • a single code/doc file — classification + rationale if applicable
    Does NOT embed code bodies; see _handler_ingest_code for the contract."""
    data = await file.read()
    filename = file.filename or "upload"
    if not title:
        title = filename.rsplit(".", 1)[0] or filename
    _debug_event(
        "ingest.code.enqueue", "Queued code ingestion job",
        title=title, filename=file.filename, content_type=file.content_type,
        bytes=len(data),
    )
    job = job_queue.submit(
        kind="ingest_code", title=title, handler=_handler_ingest_code,
        payload={"title": title, "url": url, "model": model,
                 "filename": filename, "data": data},
    )
    return {
        "job_id": job.id,
        "status": "queued",
        "queue_position": job_queue.queue_position(job.id),
        "title": title,
    }


@router.post("/api/ingest_mock")
def ingest_mock():
    """Ingest mock_sources.json through the full real pipeline."""
    data_file = os.path.join(DATA_DIR, "mock_sources.json")
    if not os.path.exists(data_file):
        raise HTTPException(status_code=404, detail="Run seed_demo_data.py first.")

    with open(data_file) as f:
        items = json.load(f)

    total_units, total_entities = 0, 0
    for item in items:
        source_id = item.get("id", str(uuid.uuid4())[:8])
        item_title = item.get("title") or item.get("id", "Mock Source")
        extraction = ingest_agent.extract_from_text(
            source_type=item.get("source_type", "other"),
            title=item_title,
            content=item.get("content", ""),
        )
        source = {
            "id": source_id,
            "kind": item.get("source_type", "other"),
            "title": item_title,
            "content": item.get("content", ""),
            "capturedAt": item.get("timestamp", _utc_now_iso()),
        }
        result = struct_agent.embed_and_store(
            source_id=source_id,
            source=source,
            units=extraction.get("units", []),
            entities=extraction.get("entities", []),
            relationships=extraction.get("relationships", []),
            raw_chunks=_chunk_text(item.get("content", ""), max_chars=_MAX_EXTRACTION_CHARS),
        )
        total_units += result["units_stored"]
        total_entities += result["entities_stored"]

    return {
        "message": "Mock data ingested through full pipeline.",
        "total_units": total_units,
        "total_entities": total_entities,
        "chroma_total": collection.count(),
    }


