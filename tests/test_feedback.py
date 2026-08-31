"""Feedback loop: the second gated write path and same-process reindex.

Two properties matter. The endpoint must refuse anything unconfirmed or
malformed and must append in the corpus file's committed one-line-per-entry
style. And a corpus edit must become retrievable IN THE SAME PROCESS,
because the API server appends feedback and then plans again without
restarting; that is exactly what the delete_collection rebuild exists for.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from src import config
    from src.api import app as app_mod

    data_dir = tmp_path / "data"
    runs_dir = tmp_path / "runs"
    data_dir.mkdir()
    runs_dir.mkdir()
    shutil.copy2(ROOT / "data" / "excursions.json", data_dir / "excursions.json")
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "RUNS_DIR", runs_dir)
    return TestClient(app_mod.app)


def test_unconfirmed_feedback_is_refused(client):
    response = client.post("/api/feedback", json={
        "kind": "outing", "date": "2026-09-05", "type": "birding",
        "site": "Prospect Park", "rating": 8, "notes": "good morning out",
    })
    assert response.status_code == 400
    assert "confirmed" in response.json()["detail"]


def test_outing_requires_rating_and_notes(client):
    base = {"kind": "outing", "date": "2026-09-05", "type": "birding",
            "site": "Prospect Park", "confirmed": True}
    assert client.post("/api/feedback",
                       json={**base, "notes": "fine"}).status_code == 400
    assert client.post("/api/feedback",
                       json={**base, "rating": 11, "notes": "fine"}).status_code == 400
    assert client.post("/api/feedback",
                       json={**base, "rating": 8}).status_code == 400


def test_decision_requires_accepted(client):
    response = client.post("/api/feedback", json={
        "kind": "decision", "date": "2026-09-05", "type": "hike",
        "site": "Harriman State Park", "confirmed": True,
    })
    assert response.status_code == 400
    assert "accepted" in response.json()["detail"]


def test_append_preserves_style_and_assigns_next_id(client, tmp_path):
    corpus = tmp_path / "data" / "excursions.json"
    before = corpus.read_text()
    # The live corpus legitimately grows as the user logs feedback, so the
    # expectation is computed from the file, not hardcoded.
    n = len(json.loads(before))
    response = client.post("/api/feedback", json={
        "kind": "decision", "date": "2026-09-05", "type": "hike",
        "site": "Harriman State Park", "accepted": False,
        "notes": "too long a transit day this week", "agent_score": 7.5,
        "confirmed": True,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == f"e{n + 1:02d}"
    assert body["count"] == n + 1

    after = corpus.read_text()
    entries = json.loads(after)
    entry = entries[-1]
    assert entry["kind"] == "decision"
    assert entry["accepted"] is False
    assert entry["source"] == "user"
    assert entry["season"] == "fall"
    assert entry["agent_score"] == 7.5
    assert "rating" not in entry
    # One line per entry, same as the committed file.
    assert len(after.splitlines()) == len(before.splitlines()) + 1


def test_same_process_reindex_serves_new_entry(tmp_path, monkeypatch):
    """The chroma client is cached per path in-process; the rebuild must go
    through delete_collection on that SAME client or a running server keeps
    serving the old corpus (the bug this test pins)."""
    from src.memory import retrieval

    corpus_path = tmp_path / "excursions.json"
    entries = json.loads((ROOT / "data" / "excursions.json").read_text())[:6]
    corpus_path.write_text(json.dumps(entries))
    monkeypatch.setattr(retrieval, "DATA_PATH", corpus_path)
    monkeypatch.setattr(retrieval, "PERSIST_DIR", tmp_path / "chroma")
    monkeypatch.setattr(retrieval, "CORPUS_HASH_PATH", tmp_path / "corpus.sha256")

    memory = retrieval.ExcursionMemory.build()
    assert memory.doc_count == 6

    entries.append({
        "id": "e99", "date": "2026-07-11", "season": "summer",
        "type": "kayaking", "site": "Sebago Canoe Club",
        "kind": "decision", "accepted": True, "source": "user",
        "notes": "calm water paddle out of the canoe club, took the "
                 "suggestion and loved the quiet basin at slack tide",
    })
    corpus_path.write_text(json.dumps(entries))

    rebuilt = retrieval.ExcursionMemory.build()  # same process, hash changed
    assert rebuilt.doc_count == 7
    result = rebuilt.retrieve(retrieval.PlanningContext(
        label="test", season="summer", activity_type="kayaking",
        site="Sebago Canoe Club", time_of_day="morning",
        day_of_week="Saturday", window="06:00-14:00"))
    assert any(c.entry_id == "e99" for c in result.kept), (
        "the entry added after the first build must be retrievable "
        "without a process restart")
