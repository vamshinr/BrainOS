"""Reset clears every store (scoped to the test namespace)."""

from __future__ import annotations

from mnemosyne.fixtures import seed_incident


def test_reset_clears_all_stores(service):
    seed_incident(service)
    assert len(service.graph.all_events()) == 8
    assert service.vector.count() > 0

    out = service.reset()
    assert out["ok"] is True
    assert out["cleared"]["events"] == 8

    assert service.graph.all_events() == []
    assert service.graph.all_edges() == []
    assert service.vector.count() == 0
