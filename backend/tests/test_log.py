from sqlalchemy import select

from app.models import ActionLog, JournalEntry


def _log(client, text, **extra):
    r = client.post("/log", json={"text": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_log_time_links_journal(client, session):
    out = _log(client, "climb 2h vital")
    assert out["parsed"] is True and out["error"] is None
    assert out["actions"][0]["result"]["time_entry"]["duration_min"] == 120
    assert "Climbing" in out["message"]
    journal = session.get(JournalEntry, out["journal_entry_id"])
    assert journal.raw_text == "climb 2h vital" and journal.input_type == "typed"
    log = session.get(ActionLog, out["actions"][0]["action_id"])
    assert log.journal_entry_id == journal.id


def test_unparsed_text_is_kept(client, session):
    out = _log(client, "honestly kind of a rough day")
    assert out["parsed"] is False and out["actions"] == []
    assert session.get(JournalEntry, out["journal_entry_id"]) is not None


def test_action_error_keeps_journal(client, session):
    out = _log(client, "stop")
    assert out["error"] == "no timer is running"
    assert out["actions"] == []
    assert session.get(JournalEntry, out["journal_entry_id"]) is not None


def test_clock_in_out_flow_and_undo(client):
    _log(client, "clocking in for tutoring", at="2026-11-17T15:00:00")
    out = _log(client, "clock out", at="2026-11-17T18:00:00")
    assert out["actions"][0]["result"]["time_entry"]["duration_min"] == 180
    undo = client.post(f"/actions/{out['actions'][0]['action_id']}/undo")
    assert undo.status_code == 200
    assert client.get("/timer").json()["job"] == "tutoring"


def test_done_completes_matching_task(client):
    task = client.post("/tasks", json={"title": "PH201 slides", "category": "SI Prep"}).json()
    out = _log(client, "done ph201 slides")
    assert out["actions"][0]["action_type"] == "complete_task"
    assert out["actions"][0]["result"]["task"]["id"] == task["result"]["task"]["id"]


def test_done_ambiguous_task(client):
    client.post("/tasks", json={"title": "SI slides week 12"})
    client.post("/tasks", json={"title": "SI slides week 13"})
    out = _log(client, "done si slides")
    assert "matches several tasks" in out["error"]


def test_task_with_unknown_hashtag(client):
    out = _log(client, "task stretch #yoga")
    assert "unknown category" in out["error"]


def test_offline_at_applies_to_duration_logs(client):
    out = _log(client, "climb 2h", at="2026-11-16T20:00:00")
    entry = out["actions"][0]["result"]["time_entry"]
    # Ends when it was typed (8pm EST), not when it was uploaded.
    assert entry["started_at"].startswith("2026-11-16T23:00:00")
    assert entry["ended_at"].startswith("2026-11-17T01:00:00")


def test_every_log_creates_one_journal(client, session):
    before = len(session.scalars(select(JournalEntry)).all())
    _log(client, "climb 1h")
    _log(client, "gibberish")
    assert len(session.scalars(select(JournalEntry)).all()) == before + 2
