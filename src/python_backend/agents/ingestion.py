"""IngestionAgent: extract structured knowledge from text and images."""
from __future__ import annotations
import base64
import time
from clients.router import _resolve_override, _resolve_text_override
from core.logging import _debug_event, _log_call
from agents.prompts import EXTRACTION_SYSTEM
from agents.extraction import _parse_extraction_json, _validate_extraction

class IngestionAgent:
    """Reads raw content (text or image) and extracts structured knowledge via the LLM."""

    def _extract_chunk(
        self,
        source_type: str,
        title: str,
        chunk: str,
        model_override: str | None = None,
    ) -> dict:
        prompt = (
            f"SOURCE TYPE: {source_type}\n"
            f"TITLE: {title}\n"
            f"---\n{chunk}\n---\n\n"
            "Extract entities, knowledge units, and relationships per the system instructions."
        )
        client, model = _resolve_text_override("extraction", model_override)
        t0 = time.time()
        _debug_event(
            "extract.chunk.start",
            "Sending chunk to extraction model",
            source_type=source_type,
            title=title,
            model=model,
            chars=len(chunk),
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                # Enforces JSON output on OpenAI and vLLM; silently ignored by Claude
                # (Claude follows the prompt instruction instead).
                response_format={"type": "json_object"},
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "extraction", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"chars={len(chunk)}",
            )
            raw = _parse_extraction_json(response.choices[0].message.content)
            result = _validate_extraction(raw)
            _debug_event(
                "extract.chunk.done",
                "Extraction model returned structured data",
                model=model,
                latency_ms=latency_ms,
                units=len(result["units"]),
                entities=len(result["entities"]),
                relationships=len(result["relationships"]),
            )
            return result
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            _log_call("extraction", model, latency_ms, ok=False, note=str(e)[:80])
            _debug_event(
                "extract.chunk.error",
                "Extraction model failed — raising so job is marked failed",
                model=model,
                latency_ms=latency_ms,
                error=str(e),
            )
            raise RuntimeError(f"Extraction failed ({model}): {e}") from e

    # ~100K chars ≈ 25K tokens. Beyond this, smaller models may hit context limits.
    # Claude Sonnet handles 200K tokens; vLLM models vary. Warn, but don't block.
    # TODO: add chunking here if content regularly exceeds model context limits.
    _CONTEXT_WARN_CHARS = 100_000

    def extract_from_text(self, source_type: str, title: str, content: str, model_override: str | None = None) -> dict:
        _debug_event(
            "extract.text.start",
            "Sending full text to extraction model",
            source_type=source_type,
            title=title,
            chars=len(content),
            model_override=model_override,
        )
        if len(content) > self._CONTEXT_WARN_CHARS:
            _debug_event(
                "extract.text.size_warning",
                "Content is large — may hit context limits on smaller models",
                chars=len(content),
                warn_threshold=self._CONTEXT_WARN_CHARS,
                estimated_tokens=len(content) // 4,
            )
        result = self._extract_chunk(source_type, title, content, model_override=model_override)
        _debug_event(
            "extract.text.done",
            "Extraction complete",
            source_type=source_type,
            units=len(result["units"]),
            entities=len(result["entities"]),
            relationships=len(result["relationships"]),
        )
        return result

    def describe_image(self, image_data: bytes, mime_type: str = "image/png", model_override: str | None = None) -> str:
        """
        VLM step: convert an image to a rich text description suitable for RAG.
        Requires a vision-capable model at VLM_API_BASE.
        """
        b64 = base64.b64encode(image_data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64}"
        client, model = _resolve_override("vlm", model_override)
        t0 = time.time()
        _debug_event(
            "image.describe.start",
            "Sending image to vision model",
            mime_type=mime_type,
            bytes=len(image_data),
            model=model,
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {
                            "type": "text",
                            "text": (
                                "You are the vision module of a Company Brain. Your description "
                                "feeds a downstream text extractor that will turn it into atomic "
                                "knowledge units. Be specific, named, and grounded.\n\n"
                                "Describe in plain prose (no lists, no markdown):\n"
                                "1. Every readable text element, transcribed verbatim where possible.\n"
                                "2. Every named system, service, person, team, or component shown.\n"
                                "3. Every visual relationship — arrows, containment, data flows, "
                                "deployment topology. Translate them into explicit sentences:\n"
                                "   • A box containing B → 'A includes B'.\n"
                                "   • Arrow from A to B labeled 'writes' → 'A writes to B'.\n"
                                "   • Dotted line → 'A optionally calls B'.\n"
                                "4. Any owner names, environments (prod/staging), regions, or versions.\n"
                                "5. Anything resembling a process step, decision, or policy.\n\n"
                                "Do NOT speculate beyond what is visible. Do NOT add a summary or "
                                "introduction. Start with the most important entity in the image."
                            ),
                        },
                    ],
                }],
                max_tokens=1024,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "vlm", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"image {len(image_data)} bytes",
            )
            description = response.choices[0].message.content
            _debug_event(
                "image.describe.done",
                "Vision model returned description",
                model=model,
                latency_ms=latency_ms,
                chars=len(description or ""),
            )
            return description
        except Exception as e:
            _log_call("vlm", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            _debug_event(
                "image.describe.error",
                "Vision model failed",
                model=model,
                latency_ms=int((time.time() - t0) * 1000),
                error=e,
            )
