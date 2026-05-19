"""brain.json read/write helpers — the shared state between all agents."""
from __future__ import annotations
import json
import threading
from config import BRAIN_JSON

_json_lock = threading.Lock()


def _read_brain() -> dict:
    try:
        with open(BRAIN_JSON, "r") as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("sources", [])
    state.setdefault("entities", [])
    state.setdefault("units", [])
    state.setdefault("relationships", [])
    state.setdefault("rawChunks", [])
    return state


def _write_brain(state: dict):
    with _json_lock:
        with open(BRAIN_JSON, "w") as f:
            json.dump(state, f, indent=2)
