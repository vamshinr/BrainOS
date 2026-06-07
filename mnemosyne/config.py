"""Configuration, read from the environment only (never hardcode secrets).

Loads, in priority order: ``mnemosyne/.env`` (highest), repo ``.env.local``, and the
legacy ``src/python_backend/.env`` (so an existing CLAUDE_API_KEY is reused). The
first definition wins (``override=False``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent

for _env_file in (
    _PKG_DIR / ".env",
    _REPO_ROOT / ".env.local",
    _REPO_ROOT / "src" / "python_backend" / ".env",
):
    if _env_file.exists():
        load_dotenv(_env_file, override=False)


def _s(name: str, default: str = "") -> str:
    val = os.getenv(name)
    return val if val not in (None, "") else default


def _f(name: str, default: float) -> float:
    try:
        return float(_s(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(_s(name, str(default)))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    return _s(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # --- Neo4j (only graph backend) ---
    neo4j_uri: str = field(default_factory=lambda: _s("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_user: str = field(default_factory=lambda: _s("NEO4J_USER", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: _s("NEO4J_PASSWORD"))
    neo4j_database: str = field(default_factory=lambda: _s("NEO4J_DATABASE", "neo4j"))
    # Namespaced node label so Mnemosyne's events never collide with foreign :Event
    # nodes that may already exist in a shared Neo4j instance.
    neo4j_event_label: str = field(default_factory=lambda: _s("NEO4J_EVENT_LABEL", "MnemosyneEvent"))

    # --- Qdrant ---
    qdrant_url: str = field(default_factory=lambda: _s("QDRANT_URL", "http://localhost:6333"))
    qdrant_collection: str = field(default_factory=lambda: _s("QDRANT_COLLECTION", "mnemosyne_events"))

    # --- Embeddings ---
    embedding_model: str = field(default_factory=lambda: _s("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    embedding_dim: int = field(default_factory=lambda: _i("EMBEDDING_DIM", 384))

    # --- LLM ---
    anthropic_api_key: str = field(
        default_factory=lambda: _s("ANTHROPIC_API_KEY") or _s("CLAUDE_API_KEY")
    )
    extraction_model: str = field(
        default_factory=lambda: _s("EXTRACTION_MODEL", "claude-haiku-4-5-20251001")
    )
    # Per project directive: causal judgment uses Haiku only (never Sonnet/other).
    judgment_model: str = field(
        default_factory=lambda: _s("JUDGMENT_MODEL", "claude-haiku-4-5-20251001")
    )

    # --- Causal engine tuning ---
    confidence_threshold: float = field(default_factory=lambda: _f("CONFIDENCE_THRESHOLD", 0.55))
    temporal_tau_s: float = field(default_factory=lambda: _f("TEMPORAL_TAU_S", 1800.0))
    temporal_max_window_s: float = field(default_factory=lambda: _f("TEMPORAL_MAX_WINDOW_S", 21600.0))
    weight_temporal: float = field(default_factory=lambda: _f("WEIGHT_TEMPORAL", 0.3))
    weight_linguistic: float = field(default_factory=lambda: _f("WEIGHT_LINGUISTIC", 0.2))
    weight_llm: float = field(default_factory=lambda: _f("WEIGHT_LLM", 0.5))
    dedup_similarity: float = field(default_factory=lambda: _f("DEDUP_SIMILARITY", 0.92))
    dedup_time_window_s: float = field(default_factory=lambda: _f("DEDUP_TIME_WINDOW_S", 3600.0))
    salience_half_life_s: float = field(default_factory=lambda: _f("SALIENCE_HALF_LIFE_S", 604800.0))
    forward_traversal: bool = field(default_factory=lambda: _b("FORWARD_TRAVERSAL", True))
    anchor_top_k: int = field(default_factory=lambda: _i("ANCHOR_TOP_K", 5))
    max_hops: int = field(default_factory=lambda: _i("MAX_HOPS", 12))

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
