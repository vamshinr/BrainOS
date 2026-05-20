"""Sensitive-topic blocklist and export token gating."""
from __future__ import annotations
import re
from config import SENSITIVE_TOPICS, EXPORT_TOKEN  # re-export for consumers

_COMPILED: list[re.Pattern] = []


def _build_patterns():
    global _COMPILED
    _COMPILED = [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in SENSITIVE_TOPICS]


_build_patterns()


def _is_sensitive(query: str) -> str | None:
    """Return the matched topic string if the query touches a sensitive topic, else None."""
    for topic, pat in zip(SENSITIVE_TOPICS, _COMPILED):
        if pat.search(query):
            return topic
    return None
