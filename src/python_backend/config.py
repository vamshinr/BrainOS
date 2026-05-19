"""Central configuration: env vars, file paths, and constants. No local imports."""
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────────────────
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR             = os.environ.get("BRAIN_DATA_DIR") or os.path.join(_project_root, "data")
CHROMA_PATH          = os.path.join(DATA_DIR, "chroma_db")
BRAIN_JSON           = os.path.join(DATA_DIR, "brain.json")
DECISION_ALERTS_JSON = os.path.join(DATA_DIR, "decision_alerts.json")
ONBOARDING_FILE      = os.path.join(DATA_DIR, "onboarding.json")
SLACK_TOKEN_FILE     = os.path.join(DATA_DIR, "slack", "oauth_tokens.json")
SLACK_CHANNEL_MAP_FILE = os.path.join(DATA_DIR, "slack", "channel_map.json")
os.makedirs(DATA_DIR, exist_ok=True)

# ── LLM provider ───────────────────────────────────────────────────────────────
LLM_PROVIDER_ENV = os.getenv("LLM_PROVIDER", "").strip().lower()
LLM_API_BASE     = (os.getenv("LLM_API_BASE") or os.getenv("VLLM_API_BASE") or "").strip()
VLM_API_BASE     = (os.getenv("VLM_API_BASE") or "").strip()
CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY", "").strip()
CLAUDE_MODEL     = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── Embedding ──────────────────────────────────────────────────────────────────
EMBEDDING_API_BASE = os.getenv("EMBEDDING_API_BASE", "")
EMBEDDING_MODEL    = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# ── Security ───────────────────────────────────────────────────────────────────
EXPORT_TOKEN = os.getenv("EXPORT_TOKEN", "").strip()
SENSITIVE_TOPICS: list[str] = [
    t.strip()
    for t in os.getenv("SENSITIVE_TOPICS", "").split(",")
    if t.strip()
]

# ── Slack polling ──────────────────────────────────────────────────────────────
SLACK_POLLER_ENABLED  = os.getenv("SLACK_POLLER_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
SLACK_POLLER_INTERVAL = float(os.getenv("SLACK_POLLER_INTERVAL_S", "15") or 15)

# ── Alert thresholds ───────────────────────────────────────────────────────────
ALERT_MIN_CONFIDENCE = float(os.getenv("DECISION_ALERT_MIN_CONFIDENCE", "0.75") or 0.75)
CEO_ALERT_KINDS      = {"decision", "policy", "ownership"}
