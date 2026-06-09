"""Reset is now a BLANKET wipe: the entire Neo4j DB + all Qdrant collections.

Because that is destructive to the whole database (not just the test namespace), this
test is OPT-IN: set MNEMOSYNE_DESTRUCTIVE_TESTS=1 to run it. The safe, namespace-scoped
clear() path is still exercised by the graph/vector fixture setup/teardown.
"""

from __future__ import annotations

import os

import pytest

from mnemosyne.fixtures import seed_incident

pytestmark = pytest.mark.skipif(
    os.getenv("MNEMOSYNE_DESTRUCTIVE_TESTS") != "1",
    reason="destructive: wipes the entire Neo4j DB + all Qdrant collections; "
    "set MNEMOSYNE_DESTRUCTIVE_TESTS=1 to run",
)


def test_reset_blanket_wipes_every_store(service):
    seed_incident(service)
    assert len(service.graph.all_events()) == 8
    assert service.vector.count() > 0

    # A node OUTSIDE the Mnemosyne namespace must ALSO be removed by a blanket reset.
    service.graph._run("CREATE (n:ForeignProbe {id: 'reset-probe'})")
    assert service.graph._run("MATCH (n) RETURN count(n) AS c")[0]["c"] >= 9

    out = service.reset()
    assert out["ok"] is True
    assert out["cleared"]["events"] == 8

    assert service.graph.all_events() == []
    assert service.graph.all_edges() == []
    assert service.vector.count() == 0
    # blanket: even the foreign-label node is gone
    assert service.graph._run("MATCH (n) RETURN count(n) AS c")[0]["c"] == 0
