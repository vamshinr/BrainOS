from mnemosyne.jobs.models import Job, make_title


def test_make_title_prefers_title_then_source_then_snippet():
    assert make_title("My Title", "src", "some text") == "My Title"
    assert make_title("", "src", "some text") == "src"
    assert make_title("", "", "short event") == "short event"
    assert make_title("", "", "x" * 100) == "x" * 40
    assert make_title("", "", "   ") == "Untitled"


def test_to_public_uses_camelcase_and_hides_payload():
    j = Job(id="1", kind="ingest_text", title="t", text="secret", source_id="s")
    pub = j.to_public()
    assert set(pub) == {
        "id", "kind", "title", "status", "progress",
        "step", "error", "createdAt", "startedAt", "finishedAt",
    }
    assert "text" not in pub
    assert pub["status"] == "queued"
    assert pub["progress"] == 0.0
    assert pub["createdAt"]
