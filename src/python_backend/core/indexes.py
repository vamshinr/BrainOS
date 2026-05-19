"""In-memory BM25 + entity indexes rebuilt from brain state on each ingest."""
from __future__ import annotations
import re
from typing import Optional
from rank_bm25 import BM25Okapi
from core.entities import _fallback_entities_from_text, _ENTITY_TOKEN_RE

# ── In-memory BM25 + entity indexes ───────────────────────────────────────────
_bm25_index: object = None           # BM25Okapi instance (None until first ingest)
_bm25_unit_ids: list[str] = []       # parallel to _bm25_corpus
_bm25_corpus: list[str] = []         # searchable unit text
_chunk_bm25_index: object = None     # BM25Okapi over raw source chunks
_chunk_ids: list[str] = []           # parallel to _chunk_corpus
_chunk_corpus: list[str] = []        # searchable raw chunk text
_entity_index: dict[str, set[str]] = {}  # entity_name_lower → {unit_id, ...}


def _tokenize_search(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_.:/-]*", text.lower())


def _unit_search_text(unit: dict) -> str:
    evidence = " ".join(
        e.get("quote", "") for e in unit.get("evidence", [])
        if isinstance(e, dict)
    )
    temporal = " ".join(str(unit.get(k, "")) for k in (
        "validFrom", "validTo", "effectiveDate", "observedAt", "supersededAt", "temporalStatus",
    ))
    return " ".join([
        unit.get("statement", ""),
        unit.get("subject", ""),
        unit.get("kind", ""),
        unit.get("department", ""),
        unit.get("sector", ""),
        temporal,
        " ".join(unit.get("entities", [])),
        evidence,
    ])


def _build_indexes(brain: dict):
    """Rebuild BM25 + entity indexes from brain state. Called on startup and after every ingest."""
    global _bm25_index, _bm25_unit_ids, _bm25_corpus, _chunk_bm25_index, _chunk_ids, _chunk_corpus, _entity_index
    indexable = [u for u in brain.get("units", []) if u.get("id")]
    _bm25_unit_ids = [u["id"] for u in indexable]
    _bm25_corpus   = [_unit_search_text(u) for u in indexable]
    tokenized      = [_tokenize_search(stmt) for stmt in _bm25_corpus]
    _bm25_index    = BM25Okapi(tokenized) if tokenized else None

    chunks = [c for c in brain.get("rawChunks", []) if c.get("id") and c.get("text")]
    _chunk_ids = [c["id"] for c in chunks]
    _chunk_corpus = [c.get("text", "") for c in chunks]
    chunk_tokenized = [_tokenize_search(text) for text in _chunk_corpus]
    _chunk_bm25_index = BM25Okapi(chunk_tokenized) if chunk_tokenized else None

    _entity_index  = {}
    for u in indexable:
        subject = u.get("subject", "").lower().strip()
        if subject:
            _entity_index.setdefault(subject, set()).add(u["id"])
        for ent in u.get("entities", []):
            key = ent.lower().strip()
            if key:
                _entity_index.setdefault(key, set()).add(u["id"])
        for alias in _fallback_entities_from_text(_unit_search_text(u)):
            key = alias.lower().strip()
            if key:
                _entity_index.setdefault(key, set()).add(u["id"])

def _rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion — combines ranked lists of unit IDs without weight tuning."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, uid in enumerate(ranked):
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda x: scores[x], reverse=True)


_TEMPORAL_STATUSES = {"current", "future", "expired", "historical", "unknown"}


