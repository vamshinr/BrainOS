import threading

from fastapi.testclient import TestClient

from mnemosyne.api import deps
from mnemosyne.api.app import app
from mnemosyne.jobs.manager import JobManager


def test_enqueue_then_snapshot_then_cancel():
    block = threading.Event()

    def ingest(text, source_id, on_progress):
        block.wait(1)

    mgr = JobManager(ingest, workers=1)
    app.dependency_overrides[deps.get_job_manager] = lambda: mgr
    try:
        client = TestClient(app)

        r = client.post("/api/jobs/ingest", json={"text": "hello world"})
        assert r.status_code == 200
        jid = r.json()["job_id"]

        snap = client.get("/api/jobs").json()
        ids = [j["id"] for j in snap["active"] + snap["queued"]]
        assert jid in ids

        one = client.get(f"/api/jobs/{jid}")
        assert one.status_code == 200 and one.json()["id"] == jid
    finally:
        block.set()
        app.dependency_overrides.clear()
