import threading
import time

from mnemosyne.jobs.manager import JobManager


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_enqueue_runs_to_completion():
    seen = {}

    def ingest(text, source_id, on_progress):
        on_progress(0.5, "half")
        seen["text"] = text
        return {"ok": True}

    m = JobManager(ingest, workers=1)
    job = m.enqueue(text="hello", source_id="s", title="t")
    assert _wait(lambda: m.get(job.id).status == "completed")
    j = m.get(job.id)
    assert j.progress == 1.0 and j.step == "Done"
    assert seen["text"] == "hello"


def test_progress_is_reported_to_the_job():
    released = threading.Event()

    def ingest(text, source_id, on_progress):
        on_progress(0.42, "working")
        released.wait(2)

    m = JobManager(ingest, workers=1)
    job = m.enqueue(text="x")
    assert _wait(lambda: m.get(job.id).progress == 0.42)
    assert m.get(job.id).step == "working"
    released.set()


def test_failure_is_captured():
    def ingest(text, source_id, on_progress):
        raise ValueError("boom")

    m = JobManager(ingest, workers=1)
    job = m.enqueue(text="x")
    assert _wait(lambda: m.get(job.id).status == "failed")
    assert "boom" in (m.get(job.id).error or "")


def test_cancel_queued_job_never_runs():
    started = []
    block = threading.Event()

    def ingest(text, source_id, on_progress):
        started.append(text)
        block.wait(2)

    m = JobManager(ingest, workers=1)
    j1 = m.enqueue(text="first")
    assert _wait(lambda: m.get(j1.id).status == "running")
    j2 = m.enqueue(text="second")
    assert _wait(lambda: j2.id in [q["id"] for q in m.snapshot()["queued"]])
    canceled = m.cancel(j2.id)
    assert canceled.status == "canceled"
    block.set()
    assert _wait(lambda: m.get(j1.id).status == "completed")
    assert "second" not in started


def test_two_jobs_run_in_parallel():
    block = threading.Event()

    def ingest(text, source_id, on_progress):
        block.wait(2)

    m = JobManager(ingest, workers=2)
    a = m.enqueue(text="a")
    b = m.enqueue(text="b")
    assert _wait(lambda: len(m.snapshot()["active"]) == 2)
    block.set()
    assert _wait(
        lambda: m.get(a.id).status == "completed" and m.get(b.id).status == "completed"
    )


def test_version_increments_on_change():
    def ingest(text, source_id, on_progress):
        return None

    m = JobManager(ingest, workers=1)
    v0 = m.version()
    job = m.enqueue(text="x")
    assert m.version() > v0
    assert _wait(lambda: m.get(job.id).status == "completed")
