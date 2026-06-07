"""Acceptance Test 2 — associative baseline surfaces the distractors (the failure mode)."""

from __future__ import annotations

from mnemosyne.fixtures import incident_query, seed_incident


def test_associative_surfaces_distractors(service):
    ev = seed_incident(service)
    res = service.retrieve(incident_query(), k=5, mode="associative")

    assert res["mode"] == "associative"
    ids = [chunk["id"] for chunk in res["chunks"]]

    # The bag-of-similar-chunks baseline pulls in keyword-similar distractors that the
    # causal traversal correctly excludes.
    assert ev["d1"].id in ids or ev["d2"].id in ids
