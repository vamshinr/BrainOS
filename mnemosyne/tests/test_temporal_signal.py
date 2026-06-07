"""Signal 1 — temporal precedence + proximity, in isolation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mnemosyne.models import Event
from mnemosyne.pipeline.causal import temporal_score

TAU = 1800.0
MAXW = 21600.0
_BASE = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def _ev(minutes: float) -> Event:
    return Event(summary="x", occurred_at=_BASE + timedelta(minutes=minutes))


def test_simultaneous_is_max():
    assert temporal_score(_ev(0), _ev(0), tau_s=TAU, max_window_s=MAXW) == 1.0


def test_decays_with_gap():
    near = temporal_score(_ev(0), _ev(5), tau_s=TAU, max_window_s=MAXW)
    far = temporal_score(_ev(0), _ev(60), tau_s=TAU, max_window_s=MAXW)
    assert near is not None and far is not None
    assert near > far > 0.0


def test_cause_after_effect_is_pruned():
    assert temporal_score(_ev(10), _ev(0), tau_s=TAU, max_window_s=MAXW) is None


def test_beyond_window_is_pruned():
    # 3 weeks gap -> way beyond the 6h window
    assert temporal_score(_ev(0), _ev(60 * 24 * 21), tau_s=TAU, max_window_s=MAXW) is None
