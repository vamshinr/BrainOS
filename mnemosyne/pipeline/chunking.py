"""Split large text into chunks for the extraction LLM.

Chunks are boundary-aware (snapped to a sentence/paragraph break near the target size)
and non-overlapping. Cross-chunk continuity is provided separately by handing each chunk
the *tail* of the previous one as read-only context (a sliding window — the L1 layer of
the chunking design), so an event that references earlier text still resolves without
being extracted twice.
"""

from __future__ import annotations


def chunk_text(text: str, *, size: int) -> list[str]:
    """Return ``text`` split into non-overlapping chunks of roughly ``size`` characters,
    each ending on a sentence/paragraph boundary where possible. Together the chunks
    cover the whole input (no text dropped)."""
    text = text.strip()
    if size <= 0 or len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            # Prefer to cut on a paragraph or sentence boundary in the latter half.
            cut = max(
                window.rfind("\n"),
                window.rfind(". "),
                window.rfind("! "),
                window.rfind("? "),
            )
            if cut > size // 2:
                end = start + cut + 1
        if end <= start:  # safety: always make progress
            end = min(start + size, n)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks
