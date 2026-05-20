"""Anthropic Claude API client with OpenAI-compatible interface."""
from __future__ import annotations
import os
from types import SimpleNamespace
import httpx
from clients.vllm import _to_obj

def _openai_messages_to_anthropic(messages: list) -> tuple[str | None, list]:
    """Split system prompt out and convert image_url blocks to Anthropic format."""
    system = None
    converted = []
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            system = m.get("content", "")
            continue
        content = m.get("content")
        if isinstance(content, str):
            converted.append({"role": role, "content": content})
        elif isinstance(content, list):
            blocks = []
            for block in content:
                if block.get("type") == "text":
                    blocks.append({"type": "text", "text": block["text"]})
                elif block.get("type") == "image_url":
                    url = block["image_url"]["url"]
                    if url.startswith("data:"):
                        header, b64data = url.split(",", 1)
                        media_type = header.split(";")[0].split(":")[1]
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64data},
                        })
                    else:
                        blocks.append({
                            "type": "image",
                            "source": {"type": "url", "url": url},
                        })
            converted.append({"role": role, "content": blocks})
        else:
            converted.append({"role": role, "content": str(content)})
    return system, converted


class _ClaudeChatCompletions:
    def __init__(self, http: httpx.Client):
        self._http = http

    def create(self, *, model, messages, max_tokens=None, temperature=None, **kwargs):
        system, converted = _openai_messages_to_anthropic(messages)
        payload: dict = {"model": model, "messages": converted, "max_tokens": max_tokens or 4096}
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature
        r = self._http.post("/messages", json=payload)
        r.raise_for_status()
        data = r.json()
        # Translate Anthropic response → OpenAI-style SimpleNamespace
        text = data["content"][0]["text"] if data.get("content") else ""
        usage = data.get("usage", {})
        return _to_obj({
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            },
            "model": model,
        })


class _ClaudeChat:
    def __init__(self, http: httpx.Client):
        self.completions = _ClaudeChatCompletions(http)


class _ClaudeModels:
    def __init__(self, model: str):
        self._model = model

    def list(self):
        return _to_obj({"data": [{"id": self._model}]})


class ClaudeAPIClient:
    """Drop-in replacement for VLLMClient backed by Anthropic Messages API via httpx."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        http = httpx.Client(
            base_url="https://api.anthropic.com/v1",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=600.0,
        )
        self.base_url = "https://api.anthropic.com/v1"
        self._model = model
        self.chat = _ClaudeChat(http)
        self.models = _ClaudeModels(model)
        self.embeddings = None  # Anthropic has no embeddings; sentence-transformers handles this


def _probe_endpoint(url: str, timeout: float = 5.0) -> bool:
    """Return True if the endpoint responds to GET /models within timeout."""
    try:
        r = httpx.get(f"{url.rstrip('/')}/models", timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

