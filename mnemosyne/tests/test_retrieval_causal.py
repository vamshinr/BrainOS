"""Acceptance Test 1 — causal retrieval over the seeded incident scenario.

retrieve("Why did checkout start throwing 500s?", mode="causal") must return the chain
e1 -> e2 -> e3 -> e4 (+ optionally e5 -> e6), time-ordered, with e1 as root, and d1/d2
in excluded_distractors.
"""

from __future__ import annotations

from mnemosyne.fixtures import incident_query, seed_incident


def test_causal_chain_and_excluded_distractors(service):
    ev = seed_incident(service)
    by_id = {ev[name].id: name for name in ev}

    res = service.retrieve(incident_query(), k=8, mode="causal")
    chain_ids = [entry["event"]["id"] for entry in res["chain"]]
    chain_names = [by_id[i] for i in chain_ids]

    # The full causal path is present...
    for name in ("e1", "e2", "e3", "e4"):
        assert ev[name].id in chain_ids, f"{name} missing from causal chain"

    # ...time-ordered root -> outcome...
    assert (
        chain_names.index("e1")
        < chain_names.index("e2")
        < chain_names.index("e3")
        < chain_names.index("e4")
    )

    # ...rooted at e1 with no incoming edge...
    assert res["chain"][0]["event"]["id"] == ev["e1"].id
    assert res["chain"][0]["incoming_relation"] is None

    # ...anchored on the checkout-500s event...
    assert res["anchor_event_id"] == ev["e4"].id

    # ...and the keyword-similar distractors are excluded from the causal path.
    assert ev["d1"].id not in chain_ids
    assert ev["d2"].id not in chain_ids
    assert set(res["excluded_distractors"]) == {ev["d1"].id, ev["d2"].id}


def test_forward_traversal_captures_resolution(service):
    ev = seed_incident(service)
    res = service.retrieve(incident_query(), k=8, mode="causal")
    chain_ids = {entry["event"]["id"] for entry in res["chain"]}
    # rollback + recovery are reachable forward from the anchor
    assert ev["e5"].id in chain_ids
    assert ev["e6"].id in chain_ids
