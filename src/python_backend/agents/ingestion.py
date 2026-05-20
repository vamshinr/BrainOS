"""IngestionAgent: extract structured knowledge from text and images."""
from __future__ import annotations
import base64
import time
from clients.router import _resolve_override, _resolve_text_override
from core.logging import _debug_event, _log_call
from agents.prompts import EXTRACTION_SYSTEM
from agents.extraction import _chunk_text, _merge_extractions, _parse_extraction_json

class IngestionAgent:
    """Reads raw content (text or image) and extracts structured knowledge via the LLM."""

    def _extract_chunk(
        self,
        source_type: str,
        title: str,
        chunk: str,
        model_override: str | None = None,
        *,
        retry: bool = False,
    ) -> dict:
        retry_instructions = ""
        if retry:
            retry_instructions = (
                "\n\nThe previous pass returned no durable knowledge. Re-read carefully and "
                "extract operational facts, named services, owners, unsafe windows, APIs, "
                "policies, gotchas, dates, teams, tools, and relationships. Return empty "
                "arrays only if this chunk truly contains no company knowledge."
            )
        prompt = (
            f"SOURCE TYPE: {source_type}\n"
            f"TITLE: {title}\n"
            f"---\n{chunk}\n---\n\n"
            "Extract entities, knowledge units, and relationships per the system instructions."
            f"{retry_instructions}"
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
            retry=retry,
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.1,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "extraction", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"chunk len={len(chunk)}",
            )
            parsed = _parse_extraction_json(response.choices[0].message.content)
            parsed.setdefault("entities", [])
            parsed.setdefault("units", [])
            parsed.setdefault("relationships", [])
            _debug_event(
                "extract.chunk.done",
                "Extraction model returned structured data",
                model=model,
                latency_ms=latency_ms,
                units=len(parsed.get("units", [])),
                entities=len(parsed.get("entities", [])),
                relationships=len(parsed.get("relationships", [])),
                retry=retry,
            )
            return parsed
        except Exception as e:
            _log_call("extraction", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            _debug_event(
                "extract.chunk.error",
                "Extraction model failed",
                model=model,
                latency_ms=int((time.time() - t0) * 1000),
                error=e,
            )
            return {"entities": [], "units": [], "relationships": []}

    def extract_from_text(self, source_type: str, title: str, content: str, model_override: str | None = None) -> dict:
        _debug_event(
            "extract.text.start",
            "Preparing text for extraction",
            source_type=source_type,
            title=title,
            chars=len(content),
            model_override=model_override,
        )
        chunks = _chunk_text(content, max_chars=3500, overlap=300)
        _debug_event(
            "extract.text.chunks",
            "Text chunking complete",
            source_type=source_type,
            chunks=len(chunks),
            chunk_chars=",".join(str(len(chunk)) for chunk in chunks),
        )
        results = []
        for idx, chunk in enumerate(chunks, start=1):
            result = self._extract_chunk(source_type, title, chunk, model_override=model_override)
            empty_result = not (
                result.get("units") or result.get("entities") or result.get("relationships")
            )
            if empty_result and len(chunk.strip()) >= 800:
                _debug_event(
                    "extract.chunk.retry",
                    "Retrying extraction because a substantial chunk returned no knowledge",
                    source_type=source_type,
                    title=title,
                    chunk=idx,
                    chars=len(chunk),
                )
                retry_result = self._extract_chunk(
                    source_type,
                    title,
                    chunk,
                    model_override=model_override,
                    retry=True,
                )
                if retry_result.get("units") or retry_result.get("entities") or retry_result.get("relationships"):
                    result = retry_result
            results.append(result)
        merged = _merge_extractions(results)
        _debug_event(
            "extract.text.done",
            "Merged extraction results",
            source_type=source_type,
            chunks=len(chunks),
            units=len(merged["units"]),
            entities=len(merged["entities"]),
            relationships=len(merged["relationships"]),
        )
        return merged

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
