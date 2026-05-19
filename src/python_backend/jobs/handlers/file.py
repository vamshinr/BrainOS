"""Job handler for file ingest (PDF, DOCX, TXT, MD, CSV) + text extraction utilities."""
from __future__ import annotations
import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional
from pypdf import PdfReader
from storage.brain import _read_brain
from core.logging import _debug_event
from agents import ingest_agent, struct_agent

def _handler_ingest_file(job: Job, q: JobQueue) -> dict:
    p = job.payload
    filename = p["filename"]
    data: bytes = p["data"]
    q.update_progress(job.id, step="extracting text", progress=0.05)
    text = _extract_file_text(filename, data)
    if (
        not text.strip()
        or text.startswith("[PDF has no selectable")
        or text.startswith("[PDF extraction failed")
        or text.startswith("[DOC extraction failed")
        or text.startswith("[DOCX extraction failed")
    ):
        raise RuntimeError(text if text.startswith("[") else "Could not extract any text from the file.")
    chunks = _chunk_text(text, max_chars=_MAX_EXTRACTION_CHARS)
    all_units, all_entities, all_relationships = [], [], []
    for idx, chunk in enumerate(chunks, start=1):
        q.update_progress(
            job.id,
            step=f"extracting facts (chunk {idx}/{len(chunks)})",
            progress=0.1 + 0.6 * (idx / max(len(chunks), 1)),
        )
        ex = ingest_agent.extract_from_text(p["kind"], p["title"], chunk, model_override=p.get("model"))
        all_units.extend(ex.get("units", []))
        all_entities.extend(ex.get("entities", []))
        all_relationships.extend(ex.get("relationships", []))
    used_fallback = False
    if not (all_units or all_entities or all_relationships):
        fb = _fallback_extract_from_document(p["kind"], p["title"], text)
        all_units = fb.get("units", [])
        all_entities = fb.get("entities", [])
        all_relationships = fb.get("relationships", [])
        used_fallback = True
    q.update_progress(job.id, step="reconciling + storing", progress=0.85)
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id, "kind": p["kind"], "title": p["title"],
        "content": text[:2000], "url": p.get("url"), "capturedAt": now,
        "uploadedFilename": filename, "charCount": len(text),
        "chunkCount": len(chunks),
        "extractionMode": "fallback" if used_fallback else "model",
    }
    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=all_units, entities=all_entities,
        relationships=all_relationships, raw_chunks=chunks,
    )
    return {
        "source_id": source_id, "chunks_processed": len(chunks),
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "relationships_extracted": len(all_relationships),
        "fallback_extraction": used_fallback,
        **result,
    }


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


def _fallback_extract_from_document(source_type: str, title: str, text: str) -> dict:
    """
    Last-resort extraction for readable uploaded files when the LLM returns no
    structured JSON. It preserves actionable document sentences as low-confidence
    units instead of reporting a successful zero-unit ingestion.
    """
    normalized = re.sub(r"\r\n?", "\n", text)
    raw_items = re.split(r"(?:\n\s*){2,}|(?<=[.!?])\s+(?=[A-Z0-9])|\n\s*(?:[-*•]|\d+[.)])\s+", normalized)
    candidates: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        sentence = re.sub(r"\s+", " ", item).strip(" -\t\n")
        if len(sentence) < 25 or len(sentence.split()) < 5:
            continue
        if sentence.lower() in seen:
            continue
        seen.add(sentence.lower())
        candidates.append(sentence)
        if len(candidates) >= 24:
            break

    entities = _extract_candidate_entities(text)
    entity_names = [entity["name"] for entity in entities]
    units = []
    for sentence in candidates:
        department = _infer_department(sentence)
        units.append({
            "kind": _infer_unit_kind(sentence),
            "department": department,
            "subject": title,
            "statement": sentence if title.lower() in sentence.lower() else f"{title}: {sentence}",
            "entities": [name for name in entity_names if name.lower() in sentence.lower()][:8],
            "evidence_quote": sentence[:500],
            "confidence": 0.55,
            "sector": _infer_sector(department),
            "valid_from": "",
            "valid_to": "",
            "effective_date": "",
            "observed_at": "",
            "temporal_status": "unknown",
        })

    relationships = []
    for sentence in candidates:
        lowered = sentence.lower()
        match = re.search(r"(.+?)\s+is owned by\s+(.+)", sentence, flags=re.IGNORECASE)
        if match:
            left = match.group(2).strip(" .,:;")
            right = match.group(1).strip(" .,:;")
            verb = "owns"
        else:
            match = re.search(r"(.+?)\s+(?:owns|responsible for|requires|uses|integrates with)\s+(.+)", sentence, flags=re.IGNORECASE)
            if not match:
                continue
            left = match.group(1).strip(" .,:;")
            right = match.group(2).strip(" .,:;")
            verb = "owns"
            if "requires" in lowered:
                verb = "requires"
            elif "uses" in lowered:
                verb = "uses"
            elif "integrates with" in lowered:
                verb = "integrates-with"
        if not (left and right):
            continue
        relationships.append({"from": left[-80:], "relation": verb, "to": right[:80], "confidence": 0.45})
        if len(relationships) >= 12:
            break

    _debug_event(
        "extract.fallback.done",
        "Fallback document extraction produced structured data",
        source_type=source_type,
        title=title,
        units=len(units),
        entities=len(entities),
        relationships=len(relationships),
    )
    return {"entities": entities, "units": units, "relationships": relationships}


def _docx_paragraph_text(para: ET.Element, ns: dict[str, str]) -> str:
    parts: list[str] = []
    for node in para.iter():
        if node.tag == f"{{{ns['w']}}}t":
            parts.append(node.text or "")
        elif node.tag == f"{{{ns['w']}}}tab":
            parts.append("\t")
        elif node.tag == f"{{{ns['w']}}}br":
            parts.append("\n")
    return re.sub(r"[ \t]+\n", "\n", "".join(parts)).strip()


def _extract_docx_text(data: bytes) -> str:
    """Extract paragraphs and table text from a .docx file using the zipped Word XML."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as docx:
            xml_parts = [
                name for name in docx.namelist()
                if name == "word/document.xml" or name.startswith("word/header") or name.startswith("word/footer")
            ]
            paragraphs: list[str] = []
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            for part in xml_parts:
                root = ET.fromstring(docx.read(part))
                for para in root.findall(".//w:p", ns):
                    line = _docx_paragraph_text(para, ns)
                    if line:
                        paragraphs.append(line)
            return "\n\n".join(paragraphs)
    except Exception as e:
        return f"[DOCX extraction failed: {e}]"


def _extract_doc_text(filename: str, data: bytes) -> str:
    """
    Best-effort legacy .doc extraction. On macOS, textutil can convert old Word
    documents to text. If unavailable, ask the user to save as .docx.
    """
    textutil = shutil.which("textutil")
    if not textutil:
        return "[DOC extraction failed: legacy .doc requires macOS textutil. Save the file as .docx and upload again.]"

    with tempfile.TemporaryDirectory() as tmpdir:
        src = os.path.join(tmpdir, filename or "upload.doc")
        out = os.path.join(tmpdir, "upload.txt")
        with open(src, "wb") as f:
            f.write(data)
        try:
            subprocess.run(
                [textutil, "-convert", "txt", "-output", out, src],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            with open(out, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception as e:
            return f"[DOC extraction failed: {e}]"

def _extract_file_text(filename: str, data: bytes) -> str:
    """Extract plain text from PDF, Word, TXT, MD, or CSV uploads."""
    name = filename.lower()
    _debug_event(
        "file.extract.start",
        "Extracting text from uploaded file",
        filename=filename,
        bytes=len(data),
    )
    if name.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p for p in pages if p.strip())
            _debug_event(
                "file.extract.pdf",
                "PDF text extraction complete",
                filename=filename,
                pages=len(reader.pages),
                chars=len(text),
            )
            if not text.strip():
                return "[PDF has no selectable text — it may be a scanned/image-based PDF. Try the Image tab instead.]"
            return text
        except Exception as e:
            _debug_event(
                "file.extract.error",
                "PDF text extraction failed",
                filename=filename,
                error=e,
            )
            return f"[PDF extraction failed: {e}]"
    if name.endswith(".docx"):
        text = _extract_docx_text(data)
        _debug_event(
            "file.extract.docx",
            "DOCX text extraction complete",
            filename=filename,
            chars=len(text),
        )
        return text
    if name.endswith(".doc"):
        text = _extract_doc_text(filename, data)
        _debug_event(
            "file.extract.doc",
            "DOC text extraction complete",
            filename=filename,
            chars=len(text),
        )
        return text
    # TXT / MD / CSV — decode directly
    for enc in ("utf-8", "latin-1"):
        try:
            text = data.decode(enc)
            _debug_event(
                "file.extract.text",
                "Plain text decode complete",
                filename=filename,
                encoding=enc,
                chars=len(text),
            )
            return text
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    _debug_event(
        "file.extract.text",
        "Plain text decode complete with replacement characters",
        filename=filename,
        encoding="utf-8-replace",
        chars=len(text),
    )
    return text




