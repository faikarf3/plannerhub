import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import ActionLog, Category, TimeEntry


def _undo(client, action_id, expect=200):
    r = client.post(f"/actions/{action_id}/undo")
    assert r.status_code == expect, r.text


def _timer(client):
    return client.get("/timer").json()


def test_log_time_with_range(client):
    r = client.post("/time-entries", json={
        "category": "Climbing", "started_at": "2026-11-17T14:00:00",
        "ended_at": "2026-11-17T16:00:00", "note": "vital",
    })
    assert r.status_code == 201, r.text
    entry = r.json()["result"]["time_entry"]
    assert entry["duration_min"] == 120
    assert entry["started_at"].startswith("2026-11-17T19:00:00")


def test_log_time_duration_only_estimate(client):
    r = client.post("/time-entries", json={
        "category": "Job Search", "duration_min": 60, "confirmed": False,
        "ended_at": "2026-11-17T12:00:00",
    })
    entry = r.json()["result"]["time_entry"]
    assert entry["started_at"].startswith("2026-11-17T16:00:00")
    assert entry["confirmed"] is False
    assert "(estimate)" in r.json()["summary"]


@pytest.mark.parametrize("body, needle", [
    ({"category": "Climbing", "duration_min": 1}, "under 2 minutes"),
    ({"category": "Climbing"}, "needs started_at"),
    ({"category": "Work", "duration_min": 60}, "job is required"),
    ({"category": "Work", "duration_min": 60, "job": "dishwashing"}, "unknown job"),
    ({"category": "Climbing", "started_at": "2026-11-17T16:00:00",
      "ended_at": "2026-11-17T14:00:00"}, "after started_at"),
])
def test_log_time_rejections(client, body, needle):
    r = client.post("/time-entries", json=body)
    assert r.status_code == 422
    assert needle in r.json()["detail"]


def test_update_entry_recomputes_duration_and_undo(client):
    entry = client.post("/time-entries", json={
        "category": "Climbing", "started_at": "2026-11-17T14:00:00",
        "ended_at": "2026-11-17T16:00:00",
    }).json()["result"]["time_entry"]
    r = client.patch(f"/time-entries/{entry['id']}", json={"ended_at": "2026-11-17T16:30:00"})
    assert r.json()["result"]["time_entry"]["duration_min"] == 150
    _undo(client, r.json()["action_id"])
    assert client.get(f"/time-entries/{entry['id']}").json() == entry


def test_starting_a_timer_stops_the_running_one_and_undo_reopens_it(client):
    a = client.post("/timer/start", json={"category": "SI Prep", "job": "si_prep",
                                          "at": "2026-11-17T09:00:00"}).json()
    b = client.post("/timer/start", json={"category": "Job Search",
                                          "at": "2026-11-17T10:30:00"}).json()
    first = client.get(f"/time-entries/{a['result']['time_entry']['id']}").json()
    assert first["duration_min"] == 90
    assert _timer(client)["id"] == b["result"]["time_entry"]["id"]
    assert "stopped si_prep" in b["summary"]

    _undo(client, b["action_id"])
    assert _timer(client)["id"] == first["id"]
    assert client.get(f"/time-entries/{b['result']['time_entry']['id']}").status_code == 404


def test_stop_and_undo(client):
    client.post("/timer/start", json={"category": "Climbing", "at": "2026-11-17T14:00:00"})
    r = client.post("/timer/stop", json={"at": "2026-11-17T15:45:00"})
    assert r.json()["result"]["time_entry"]["duration_min"] == 105
    assert _timer(client) is None
    _undo(client, r.json()["action_id"])
    assert _timer(client)["ended_at"] is None


def test_accidental_tap_is_dropped_and_undo_restores(client):
    start = client.post("/timer/start", json={"category": "Climbing",
                                              "at": "2026-11-17T14:00:00"}).json()
    r = client.post("/timer/stop", json={"at": "2026-11-17T14:01:00"})
    assert "Dropped" in r.json()["summary"]
    entry_id = start["result"]["time_entry"]["id"]
    assert client.get(f"/time-entries/{entry_id}").status_code == 404
    _undo(client, r.json()["action_id"])
    assert _timer(client)["id"] == entry_id


def test_stop_without_timer(client):
    assert client.post("/timer/stop").status_code == 409


def test_failed_action_leaves_no_partial_writes(client, session):
    client.post("/timer/start", json={"category": "Climbing", "at": "2026-11-17T14:00:00"})
    logs_before = len(session.scalars(select(ActionLog)).all())
    # Starting a new timer "before" the running one started must fail without stopping it.
    r = client.post("/timer/start", json={"category": "School", "at": "2026-11-17T13:00:00"})
    assert r.status_code == 422
    assert _timer(client)["ended_at"] is None
    assert len(session.scalars(select(ActionLog)).all()) == logs_before


def test_clock_in_and_out(client):
    r = client.post("/shifts/clock-in", json={"job": "tutoring", "at": "2026-11-17T15:00:00"})
    assert r.status_code == 200, r.text
    work = next(c for c in client.get("/categories").json() if c["name"] == "Work")
    assert r.json()["result"]["time_entry"]["category_id"] == work["id"]

    r = client.post("/shifts/clock-out", json={"at": "2026-11-17T18:00:00"})
    assert r.json()["result"]["time_entry"]["duration_min"] == 180


def test_clock_in_si_prep_uses_its_category(client):
    r = client.post("/shifts/clock-in", json={"job": "si_prep"})
    prep = next(c for c in client.get("/categories").json() if c["name"] == "SI Prep")
    assert r.json()["result"]["time_entry"]["category_id"] == prep["id"]


def test_clock_out_refuses_non_work_timer(client):
    client.post("/timer/start", json={"category": "Climbing"})
    assert client.post("/shifts/clock-out").status_code == 409


def test_clock_in_unknown_job(client):
    assert client.post("/shifts/clock-in", json={"job": "astronaut"}).status_code == 422


def test_db_enforces_one_running_timer(session):
    cat = session.scalar(select(Category).where(Category.name == "Personal"))
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    session.add(TimeEntry(category_id=cat.id, started_at=now))
    session.flush()
    session.add(TimeEntry(category_id=cat.id, started_at=now))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_stop_named_activity_must_match_running_timer(client):
    client.post("/timer/start", json={"category": "Work", "job": "tutoring",
                                      "at": "2026-11-17T15:00:00"})
    r = client.post("/log", json={"text": "stop climbing"}).json()
    assert r["error"] == "the running timer is tutoring, not Climbing"
    r = client.post("/log", json={"text": "stop si session"}).json()
    assert r["error"] == "the running timer is tutoring, not si_session"
    r = client.post("/log", json={"text": "stop tutoring", "at": "2026-11-17T18:00:00"}).json()
    assert r["actions"][0]["result"]["time_entry"]["duration_min"] == 180
