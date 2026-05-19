"""Brain state endpoints: read, delete unit, and hard reset."""
from __future__ import annotations
import os
import shutil
from fastapi import APIRouter, HTTPException
from storage.brain import _read_brain, _write_brain, BRAIN_JSON
from storage.chroma import collection, chroma_client, embedding_fn
from core.indexes import _build_indexes
from config import CHROMA_PATH, DATA_DIR, DECISION_ALERTS_JSON

router = APIRouter()

@router.delete("/api/units/{unit_id}")
def delete_unit(unit_id: str):
    """Remove a single unit from ChromaDB and brain.json."""
    try:
        collection.delete(ids=[unit_id])
    except Exception as e:
        print(f"[delete_unit] ChromaDB delete skipped: {e}")

    brain = _read_brain()
    brain["units"] = [u for u in brain["units"] if u["id"] != unit_id]
    _write_brain(brain)
    return {"ok": True, "unit_id": unit_id}


# ── Security gates ────────────────────────────────────────────────────────────
# Simple env-driven guards. If EXPORT_TOKEN is unset, export is open. If set,
# /api/skills_export and SKILLS.md downloads require a matching ?token=...
# SENSITIVE_TOPICS is a comma-separated list of substrings. /api/ask refuses
# queries that match any of them. Both are intentionally low-tech for the demo.
EXPORT_TOKEN = os.getenv("EXPORT_TOKEN", "").strip()
SENSITIVE_TOPICS = [
    t.strip().lower() for t in os.getenv("SENSITIVE_TOPICS", "").split(",") if t.strip()
]


def _is_sensitive(query: str) -> str | None:
    """Return the matched topic if the query touches a sensitive subject."""
    q = query.lower()
    for topic in SENSITIVE_TOPICS:
        if topic and topic in q:
            return topic
    return None


from integrations.slack_routes import create_slack_router
from slack_mcp.auth import load_slack_config
from slack_mcp.web_poller import (
    run_poller as _run_slack_poller,
    get_poller_status as _get_slack_poller_status,
)


@router.get("/api/state")
def get_state():
    """Return full brain state (sources, entities, units) for the Next.js frontend."""
    return _read_brain()


@router.delete("/api/units/{unit_id}")
def delete_unit(unit_id: str):
    """Mark a single unit as stale (soft delete) and remove it from ChromaDB."""
    brain = _read_brain()
    found = False
    for u in brain["units"]:
        if u["id"] == unit_id:
            u["stale"] = True
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")
    _write_brain(brain)
    try:
        collection.delete(ids=[unit_id])
    except Exception:
        pass
    return {"ok": True, "deleted": unit_id}


@router.delete("/api/clear")
def clear_all():
    """Hard reset of the entire RAG pipeline:
      • ChromaDB collection (sysdb row + segment .bin files via Chroma's API)
      • Any orphan segment dirs left behind by previous crashes
      • brain.json
      • uploads/ingested/snapshots dirs
      • in-memory BM25 + entity indexes

    We deliberately do NOT manually delete chroma.sqlite3 — Chroma holds an
    open SQLite handle to it, and yanking the file out from under that handle
    leaves the next operation hitting a schema-less DB ("no such table:
    collections"). Instead we use Chroma's own delete_collection() + reset()
    which clean up .bin files via the segment manager."""
    global collection
    removed: list[str] = []

    # Snapshot the active collection's segment dirs BEFORE delete_collection so
    # we know what to expect on disk afterwards (used to find true orphans in
    # step 4).
    chroma_subdirs_before: set[str] = set()
    if os.path.isdir(CHROMA_PATH):
        chroma_subdirs_before = {
            e for e in os.listdir(CHROMA_PATH)
            if os.path.isdir(os.path.join(CHROMA_PATH, e))
        }

    # 1. Drop the collection. Chroma's segment manager removes the segment
    # directory on disk (data_level0.bin, header.bin, length.bin,
    # link_lists.bin) AND the sysdb row.
    try:
        chroma_client.delete_collection("brainos_knowledge")
        removed.append("chroma:brainos_knowledge")
    except Exception as e:
        # Already gone / never existed — fine, continue.
        print(f"[BrainOS] delete_collection skipped: {e}")

    # 2. Reset the rest of the sysdb (catches any orphan collections from
    # earlier crashes). With allow_reset=True this is non-destructive to the
    # client's connection — sqlite tables are dropped and recreated empty.
    try:
        chroma_client.reset()
    except Exception as e:
        print(f"[BrainOS] chroma_client.reset() skipped: {e}")

    # 3. Recreate the collection on the SAME client. Building a new
    # PersistentClient would hit chromadb's SharedSystemClient cache and
    # return a stale handle ("readonly database") — bad.
    collection = chroma_client.get_or_create_collection(
        name="brainos_knowledge",
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    # 4. Defensive: remove any UUID-shaped segment dirs that existed BEFORE
    # the reset and weren't cleaned up by Chroma (true orphans — usually from
    # an interrupted previous reset). Safe to rmtree because they're no
    # longer referenced by any collection in the freshly-reset sysdb.
    if os.path.isdir(CHROMA_PATH):
        chroma_subdirs_after: set[str] = {
            e for e in os.listdir(CHROMA_PATH)
            if os.path.isdir(os.path.join(CHROMA_PATH, e))
        }
        # Anything that existed before but Chroma didn't touch during reset is
        # an orphan. Belt-and-suspenders only — the common case has no orphans.
        for entry in chroma_subdirs_before & chroma_subdirs_after:
            if len(entry) != 36:  # only UUID-shaped names
                continue
            full = os.path.join(CHROMA_PATH, entry)
            try:
                shutil.rmtree(full)
                removed.append(full)
            except Exception as e:
                print(f"[BrainOS] WARNING: could not remove orphan {full}: {e}")

    # 5. brain.json + decision alerts
    if os.path.exists(BRAIN_JSON):
        try:
            os.remove(BRAIN_JSON)
            removed.append(BRAIN_JSON)
        except Exception as e:
            print(f"[BrainOS] WARNING: could not remove {BRAIN_JSON}: {e}")
    if os.path.exists(DECISION_ALERTS_JSON):
        try:
            os.remove(DECISION_ALERTS_JSON)
            removed.append(DECISION_ALERTS_JSON)
        except Exception as e:
            print(f"[BrainOS] WARNING: could not remove {DECISION_ALERTS_JSON}: {e}")

    # 6. uploads / ingested / snapshots — ingest artifacts
    for sub in ("uploads", "ingested", "snapshots"):
        path = os.path.join(DATA_DIR, sub)
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                removed.append(path)
            except Exception as e:
                print(f"[BrainOS] WARNING: could not remove {path}: {e}")

    # 7. Fresh empty brain.json so the frontend sees a clean state.
    empty_state = {
        "sources": [], "entities": [], "units": [],
        "relationships": [], "rawChunks": [],
    }
    _write_brain(empty_state)

    # 8. In-memory BM25 + entity indexes (the BM25 index would otherwise still
    # hold references to the deleted units).
    _build_indexes(empty_state)

    return {"ok": True, "cleared": True, "removed": removed}


