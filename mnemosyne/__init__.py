"""Mnemosyne — a causally-indexed, event-sourced memory substrate for LLM agents.

The novel part is the *causal graph*: we store timestamped events and the directed
cause->effect edges between them, then retrieve by walking those edges (root-cause
backward, consequences forward) instead of returning a bag of similar chunks.

Honest framing: this is *approximate* causality — temporal precedence + linguistic
association + an LLM judgment — not true causal inference. That is the accepted
practical tradeoff; see ``mnemosyne.pipeline.causal``.
"""

__version__ = "0.1.0"
