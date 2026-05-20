"""
BrainOS Autonomous Agent — Gemma 4 on vLLM

Gemma 4 naturally outputs tool calls in the format:
    call:brainos:<tool_name>{"param": "value"}

This agent parses that format (no native tool_call API needed — vLLM does not
require --enable-auto-tool-choice). The system prompt instructs Gemma to use
this exact format; the parser extracts tool name + JSON args from raw text.
"""

import json
import os
import re
from collections import deque
from typing import Any

import httpx

from .prompts import build_system_prompt
from .tools import TOOL_NAMES

# ── Guardrails ────────────────────────────────────────────────────────────────

# Phrases that signal prompt injection or jailbreak attempts
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|your)\s+instructions",
    r"(you are|act as|pretend (to be|you are))\s+(a\s+)?(different|new|another|unrestricted|free)",
    r"(developer|god|admin|jailbreak|dan|sudo)\s*mode",
    r"forget\s+(your\s+)?(previous\s+)?(instructions|rules|constraints|training)",
    r"do\s+anything\s+now",
    r"you\s+have\s+no\s+restrictions",
    r"your\s+(true|real|actual)\s+(self|purpose|instructions)",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions|prompt|training)",
    r"(override|bypass|disable|ignore)\s+(your\s+)?(safety|guardrails|filters|restrictions|rules)",
    r"</?system>|</?prompt>|</?instruction>",
    r"unlock\s+(your|the)\s+(full|true|real)\s+(potential|capabilities|mode)",
    r"new\s+persona|switch\s+persona|change\s+your\s+role",
    r"anthropic|openai\s+override|google\s+override",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

# Topics clearly outside BrainOS scope — general knowledge, not company knowledge
_OUT_OF_SCOPE_PATTERNS = [
    r"\b(write|create|generate)\s+(me\s+)?(a\s+)?(poem|story|essay|song|joke|haiku|novel|script|fiction)\b",
    r"\bwhat\s+is\s+the\s+(capital|population|currency|president|prime\s+minister)\s+of\b",
    r"\b(solve|calculate|compute|what\s+is)\s+[\d\s\+\-\*\/\^\(\)=]+\b",
    r"\btranslate\s+.+\s+to\s+\w+\b",
    r"\bweather\s+in\b",
    r"\bstock\s+price\s+(of|for)\b",
    r"\b(who\s+is|what\s+is)\s+(albert einstein|napoleon|shakespeare|elon musk|taylor swift)\b",
    r"\bwrite\s+(code|a\s+function|a\s+script|a\s+program)\b",
    r"\bhelp\s+me\s+(with\s+my\s+homework|study for|pass\s+(the|my)\s+exam)\b",
]
_OUT_OF_SCOPE_RE = re.compile("|".join(_OUT_OF_SCOPE_PATTERNS), re.IGNORECASE)

# Phrases that must never appear in agent output
_OUTPUT_BLOCKLIST = [
    r"my\s+system\s+prompt\s+says",
    r"my\s+instructions\s+(say|are|tell\s+me)",
    r"i\s+was\s+told\s+to",
    r"as\s+(chatgpt|gpt|claude|gemini|llama|an?\s+ai\s+language\s+model)",
    r"i\s+(am|can\s+be)\s+jailbroken",
    r"developer\s+mode\s+(enabled|activated|on)",
    r"call:brainos:[a-z_]+\{.*?\}",  # raw tool call must never leak into final answer
]
_OUTPUT_BLOCKLIST_RE = re.compile("|".join(_OUTPUT_BLOCKLIST), re.IGNORECASE | re.DOTALL)

_REFUSAL_INJECTION = (
    "I can't help with that. I'm a company knowledge assistant — "
    "ask me about knowledge stored in BrainOS."
)
_REFUSAL_SCOPE = (
    "I'm scoped to company knowledge management only. "
    "I can help you query, store, or analyze knowledge in BrainOS — not general questions."
)
_REFUSAL_OUTPUT_BLOCKED = (
    "I wasn't able to generate a safe response. Please rephrase your question "
    "about company knowledge stored in BrainOS."
)


def _check_input(text: str) -> str | None:
    """
    Returns a refusal string if the input should be blocked, else None.
    Checks: prompt injection, jailbreak patterns, out-of-scope requests.
    """
    stripped = text.strip()

    # Hard block: injection / jailbreak
    if _INJECTION_RE.search(stripped):
        return _REFUSAL_INJECTION

    # Soft block: clearly out-of-scope general knowledge
    if _OUT_OF_SCOPE_RE.search(stripped):
        return _REFUSAL_SCOPE

    # Length sanity: reject absurdly long inputs (likely data-stuffing attack)
    if len(stripped) > 4000:
        return "Your message is too long. Please keep questions concise (under 4000 characters)."

    return None


def _sanitize_output(text: str) -> str:
    """
    Strip anything from the model output that should never reach the user:
    - Raw tool call syntax that leaked into the final answer
    - Self-referential instruction leakage
    """
    # Strip any leaked call:brainos: lines from the final answer
    text = re.sub(r"call:brainos:[a-z_]+\{[^}]*\}", "", text, flags=re.IGNORECASE)
    # Strip leaked system-prompt references
    if _OUTPUT_BLOCKLIST_RE.search(text):
        return _REFUSAL_OUTPUT_BLOCKED
    return text.strip()

AGENT_API_BASE = os.getenv("AGENT_API_BASE", os.getenv("VLLM_API_BASE", "http://165.245.128.5:8001/v1"))
AGENT_MODEL = os.getenv("AGENT_MODEL_NAME", "google/gemma-4-26b-a4b-it")
MAX_TOOL_CALLS = int(os.getenv("AGENT_MAX_TOOL_CALLS", "5"))
MAX_HISTORY_TURNS = int(os.getenv("AGENT_SESSION_TTL_TURNS", "20"))
MAX_TOOL_RESULT_CHARS = 2000

# Matches: call:brainos:<tool_name>{...}
# Gemma sometimes wraps it in backticks or adds whitespace — handle all cases
_TOOL_CALL_RE = re.compile(
    r"call:brainos:([a-z_]+)\s*(\{.*?\})",
    re.DOTALL | re.IGNORECASE,
)

_INGEST_INTENT_RE = re.compile(
    r"\b(ingest|remember|store|save|add)\b.{0,80}\b(this|to\s+(the\s+)?brain|in\s+(to\s+)?the\s+brain|knowledge|info|information)\b"
    r"|\b(this|these)\b.{0,80}\b(into|to)\s+(the\s+)?brain\b",
    re.IGNORECASE | re.DOTALL,
)


def _looks_like_ingest_request(text: str) -> bool:
    return bool(_INGEST_INTENT_RE.search(text))


def _strip_ingest_instruction(text: str) -> str:
    """
    Users often paste the source text and append "can you ingest this into the
    brain". Store the source text, not the command wrapper.
    """
    lines = text.strip().splitlines()
    while lines and _looks_like_ingest_request(lines[-1]) and len(lines[-1]) <= 180:
        lines.pop()
    cleaned = "\n".join(lines).strip()
    return cleaned or text.strip()


def _title_for_ingest(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first = re.sub(r"^[#*\-\s]+", "", first).strip()
    return (first[:76] + "…") if len(first) > 77 else (first or "Agent Ingestion")


class AgentResponse:
    def __init__(self, reply: str, tools_used: list[str], session_id: str):
        self.reply = reply
        self.tools_used = tools_used
        self.session_id = session_id

    def to_dict(self) -> dict:
        return {
            "reply": self.reply,
            "tools_used": self.tools_used,
            "session_id": self.session_id,
        }


class BrainOSAgent:
    def __init__(self, tool_executors: dict[str, Any]):
        self._client = httpx.Client(
            base_url=AGENT_API_BASE.rstrip("/"),
            timeout=120.0,
        )
        self._model = AGENT_MODEL
        self._executors = tool_executors
        self._sessions: dict[str, deque] = {}
        self._system_prompt = build_system_prompt()

    def _get_history(self, session_id: str) -> deque:
        if session_id not in self._sessions:
            self._sessions[session_id] = deque(maxlen=MAX_HISTORY_TURNS * 2)
        return self._sessions[session_id]

    def _call_llm(self, history: list[dict]) -> str:
        messages = [{"role": "system", "content": self._system_prompt}] + history
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""

    def _parse_tool_call(self, text: str) -> dict | None:
        """Parse Gemma 4's native call:brainos:<tool>{...} format."""
        match = _TOOL_CALL_RE.search(text)
        if not match:
            return None
        name = match.group(1).strip().lower()
        if name not in TOOL_NAMES:
            return None
        try:
            args = json.loads(match.group(2))
        except Exception:
            args = {}
        return {"action": name, "input": args}

    def _execute_tool(self, tool_name: str, tool_input: dict) -> str:
        executor = self._executors.get(tool_name)
        if executor is None:
            return f"[Error: tool '{tool_name}' not registered]"
        try:
            result = executor(**tool_input)
            text = json.dumps(result, default=str) if not isinstance(result, str) else result
            if len(text) > MAX_TOOL_RESULT_CHARS:
                text = text[:MAX_TOOL_RESULT_CHARS] + "… [truncated]"
            return text
        except Exception as exc:
            return f"[Tool error: {exc}]"

    def run(self, session_id: str, user_message: str) -> AgentResponse:
        # ── Input guardrail (firewall) ────────────────────────────────────────
        blocked = _check_input(user_message)
        if blocked:
            return AgentResponse(reply=blocked, tools_used=[], session_id=session_id)

        if _looks_like_ingest_request(user_message):
            ingest_text = _strip_ingest_instruction(user_message)
            title = _title_for_ingest(ingest_text)
            tool_result = self._execute_tool("ingest_text", {"text": ingest_text, "title": title})
            try:
                parsed = json.loads(tool_result)
            except Exception:
                parsed = {}

            if parsed.get("queued"):
                reply = (
                    f"Queued this for ingestion as \"{parsed.get('title', title)}\". "
                    f"Job {parsed.get('job_id')} is now in the BrainOS job dock, where extraction "
                    "and reconciliation progress will update."
                )
            else:
                reply = (
                    "I could not queue that ingestion. "
                    f"{tool_result[:500]}"
                )

            history = self._get_history(session_id)
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": reply})
            return AgentResponse(reply=reply, tools_used=["ingest_text"], session_id=session_id)

        history = self._get_history(session_id)
        history.append({"role": "user", "content": user_message})

        tools_used: list[str] = []

        for _ in range(MAX_TOOL_CALLS):
            try:
                content = self._call_llm(list(history))
            except Exception as exc:
                reply = f"I encountered an error contacting the model: {exc}"
                history.append({"role": "assistant", "content": reply})
                return AgentResponse(reply=reply, tools_used=tools_used, session_id=session_id)

            tool_call = self._parse_tool_call(content)

            if not tool_call:
                # No tool call — this is the final answer; run output guardrail
                final = _sanitize_output(content)
                if not final:
                    final = "I wasn't able to find relevant information. Try ingesting some knowledge first."
                history.append({"role": "assistant", "content": final})
                return AgentResponse(reply=final, tools_used=tools_used, session_id=session_id)

            # Execute tool
            tool_name = tool_call["action"]
            tool_input = tool_call.get("input", {})
            if tool_name == "ask_brain":
                question = str(
                    tool_input.get("question")
                    or tool_input.get("query")
                    or tool_input.get("q")
                    or ""
                ).strip()
                if not question:
                    question = user_message.strip()
                tool_input = {"question": question}
            if tool_name == "ingest_text" and not str(tool_input.get("text", "")).strip():
                ingest_text = _strip_ingest_instruction(user_message)
                tool_input = {
                    "text": ingest_text,
                    "title": tool_input.get("title") or _title_for_ingest(ingest_text),
                }
            tools_used.append(tool_name)

            tool_result = self._execute_tool(tool_name, tool_input)

            if tool_name == "ask_brain":
                history.append({"role": "assistant", "content": content})
                if tool_result.startswith("[Tool error:"):
                    reply = f"Knowledge graph lookup failed: {tool_result}"
                else:
                    try:
                        parsed = json.loads(tool_result)
                    except Exception:
                        parsed = {}
                    answer = str(parsed.get("answer") or "").strip()
                    reply = answer or "The brain does not have this information yet."
                final = _sanitize_output(reply)
                history.append({"role": "assistant", "content": final})
                return AgentResponse(reply=final, tools_used=tools_used, session_id=session_id)

            if tool_name == "ingest_text":
                history.append({"role": "assistant", "content": content})
                if tool_result.startswith("[Tool error:"):
                    reply = f"I could not queue that ingestion. {tool_result}"
                else:
                    try:
                        parsed = json.loads(tool_result)
                    except Exception:
                        parsed = {}
                    if parsed.get("queued"):
                        reply = (
                            f"Queued this for ingestion as \"{parsed.get('title', 'Agent Ingestion')}\". "
                            f"Job {parsed.get('job_id')} is now in the BrainOS job dock, where extraction "
                            "and reconciliation progress will update."
                        )
                    else:
                        reply = "I could not queue that ingestion."
                final = _sanitize_output(reply)
                history.append({"role": "assistant", "content": final})
                return AgentResponse(reply=final, tools_used=tools_used, session_id=session_id)

            # Feed result back — ask for final answer inline to save a round-trip
            history.append({"role": "assistant", "content": content})
            history.append({
                "role": "user",
                "content": (
                    f"Tool result for {tool_name}:\n{tool_result}\n\n"
                    "Write your final answer in plain text. "
                    "If you need another tool call, use call:brainos: format. "
                    "Otherwise answer directly — do not repeat the tool output verbatim."
                ),
            })

        # Max tool calls hit — force a summary
        try:
            history.append({
                "role": "user",
                "content": "Summarize what you found into a final answer in plain text. No more tool calls.",
            })
            final = _sanitize_output(self._call_llm(list(history)))
        except Exception:
            final = "I gathered information but couldn't produce a clean summary. Please try a more specific question."

        history.append({"role": "assistant", "content": final})
        return AgentResponse(reply=final, tools_used=tools_used, session_id=session_id)

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


_agent_instance: BrainOSAgent | None = None


def init_agent(tool_executors: dict[str, Any]) -> BrainOSAgent:
    global _agent_instance
    _agent_instance = BrainOSAgent(tool_executors)
    print(f"[BrainOS] Agent initialized — model: {AGENT_MODEL} @ {AGENT_API_BASE}")
    return _agent_instance


def get_agent() -> BrainOSAgent:
    if _agent_instance is None:
        raise RuntimeError("Agent not initialized — call init_agent() first")
    return _agent_instance
