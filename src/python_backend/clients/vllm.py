"""OpenAI-compatible HTTP client for vLLM (and any OpenAI-compatible endpoint)."""
from __future__ import annotations
import os
from types import SimpleNamespace
import httpx


def _to_obj(data):
    """Recursively convert JSON dicts to SimpleNamespace for attribute access."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: _to_obj(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_to_obj(v) for v in data]
    return data

def _to_obj(data):
    """Recursively convert JSON dicts to SimpleNamespace so callers can use
    attribute access (response.choices[0].message.content, etc.)."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: _to_obj(v) for k, v in data.items()})
    if isinstance(data, list):
        return [_to_obj(v) for v in data]
    return data


class _ChatCompletions:
    def __init__(self, http: httpx.Client):
        self._http = http

    def create(self, *, model, messages, max_tokens=None, temperature=None, **kwargs):
        payload = {"model": model, "messages": messages, **kwargs}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        r = self._http.post("/chat/completions", json=payload)
        r.raise_for_status()
        return _to_obj(r.json())


class _Chat:
    def __init__(self, http: httpx.Client):
        self.completions = _ChatCompletions(http)


class _Embeddings:
    def __init__(self, http: httpx.Client):
        self._http = http

    def create(self, *, model, input):
        r = self._http.post("/embeddings", json={"model": model, "input": input})
        r.raise_for_status()
        return _to_obj(r.json())


class _Models:
    def __init__(self, http: httpx.Client):
        self._http = http

    def list(self):
        r = self._http.get("/models")
        r.raise_for_status()
        return _to_obj(r.json())


class VLLMClient:
    def __init__(self, base_url: str, timeout: float = 600.0):
        self.base_url = base_url.rstrip("/")
        # Pass OPENAI_API_KEY when present so this client also works against
        # OpenAI's API (and any OpenAI-compatible endpoint that requires a
        # bearer token). Self-hosted vLLM servers ignore the header.
        headers: dict[str, str] = {}
        _key = os.getenv("OPENAI_API_KEY", "").strip()
        if _key:
            headers["Authorization"] = f"Bearer {_key}"
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers or None,
        )
        self.chat = _Chat(self._http)
        self.embeddings = _Embeddings(self._http)
        self.models = _Models(self._http)


