"""HTTP surface smoke tests (real backends, isolated test namespace)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mnemosyne.api import app as app_module
from mnemosyne.api import deps
from mnemosyne.fixtures import incident_query, seed_incident


@pytest.fixture
def client(service, monkeypatch):
    monkeypatch.setattr(deps, "get_service", lambda: service)
    return TestClient(app_module.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("neo4j") == "connected"


def test_graph_retrieve_and_event(client, service):
    ev = seed_incident(service)

    g = client.get("/graph").json()
    assert len(g["events"]) == 8
    assert len(g["edges"]) == 5

    r = client.post("/retrieve", json={"query": incident_query(), "k": 8, "mode": "causal"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "causal"
    assert set(body["excluded_distractors"]) == {ev["d1"].id, ev["d2"].id}

    r = client.get(f"/event/{ev['e4'].id}")
    assert r.status_code == 200
    assert len(r.json()["incoming_edges"]) >= 1

    assert client.get("/event/nonexistent-id").status_code == 404


def test_edge_invariant_returns_422(client, service):
    ev = seed_incident(service)
    # e4 (later) as cause of e1 (earlier) violates causes-precede-effects
    r = client.post("/edge", json={"cause_id": ev["e4"].id, "effect_id": ev["e1"].id})
    assert r.status_code == 422
