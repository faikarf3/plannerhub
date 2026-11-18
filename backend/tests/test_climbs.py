"""log_climb: new sessions, details on existing entries, undo, GET /climbs, and the
/log paths (quick-add and AI) that lead to it."""

import pytest
from sqlalchemy import select

from app.extract import ToolCall, find_invented_time, invented_time_question
from app.models import Climb, TimeEntry
from app.timeutil import to_utc
from tests.test_extract import fake  # noqa: F401  (fixture)

SESSION = {"started_at": "2026-11-17T14:00:00", "ended_at": "2026-11-17T16:00:00"}


def _climb(client, expect=201, **body):
    r = client.post("/climbs", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def _undo(client, action_id):
    r = client.post(f"/actions/{action_id}/undo")
    assert r.status_code == 200, r.text


def test_log_climb_creates_entry_and_climb(client):
    out = _climb(client, gym="Vital", notes="overhang", **SESSION)
    assert out["summary"].endswith("at Vital")
    entry, climb = out["result"]["time_entry"], out["result"]["climb"]
    assert entry["duration_min"] == 120 and climb["time_entry_id"] == entry["id"]
    assert (climb["gym"], climb["notes"]) == ("Vital", "overhang")
    listed = client.get("/time-entries", params={"start": "2026-11-17"}).json()
    assert [e["id"] for e in listed] == [entry["id"]]


def test_log_climb_duration_and_estimate(client):
    out = _climb(client, duration_min=90, confirmed=False, ended_at="2026-11-17T12:00:00")
    entry = out["result"]["time_entry"]
    assert entry["duration_min"] == 90 and entry["confirmed"] is False
    assert out["result"]["climb"]["gym"] is None


def test_gym_spelling_is_reused_and_capitalized(client):
    first = _climb(client, gym="brooklyn boulders", **SESSION)
    assert first["result"]["climb"]["gym"] == "Brooklyn Boulders"
    second = _climb(client, gym="BROOKLYN BOULDERS", duration_min=60,
                    ended_at="2026-11-18T12:00:00")
    assert second["result"]["climb"]["gym"] == "Brooklyn Boulders"


def test_undo_removes_entry_and_climb(client, session):
    out = _climb(client, gym="Vital", **SESSION)
    _undo(client, out["action_id"])
    assert session.scalars(select(TimeEntry)).all() == []
    assert session.scalars(select(Climb)).all() == []


def test_details_for_stopped_timer_then_update_and_undo(client, session):
    client.post("/timer/start", json={"category": "Climbing", "at": "2026-11-17T14:00:00"})
    entry_id = client.post("/timer/stop", json={"at": "2026-11-17T16:00:00"}
                           ).json()["result"]["time_entry"]["id"]

    added = _climb(client, time_entry_id=entry_id, gym="Vital")
    assert added["summary"] == "Saved climb details at Vital"
    changed = _climb(client, time_entry_id=entry_id, notes="sent a V5")
    climb = changed["result"]["climb"]
    assert (climb["gym"], climb["notes"]) == ("Vital", "sent a V5")

    _undo(client, changed["action_id"])
    row = session.scalar(select(Climb))
    assert (row.gym, row.notes) == ("Vital", None)
    _undo(client, added["action_id"])
    assert session.scalar(select(Climb)) is None
    assert session.get(TimeEntry, entry_id) is not None  # the time stays


@pytest.mark.parametrize("body, status, needle", [
    ({"time_entry_id": 999999, "gym": "Vital"}, 404, "not found"),
    ({"time_entry_id": "ENTRY", "duration_min": 60}, 422, "not both"),
    ({"time_entry_id": "SCHOOL", "gym": "Vital"}, 422, "not Climbing"),
    ({"duration_min": 1}, 422, "under 2 minutes"),
    ({"gym": "Vital"}, 422, "needs started_at"),
])
def test_log_climb_rejections(client, body, status, needle):
    climbing = _climb(client, **SESSION)["result"]["time_entry"]["id"]
    school = client.post("/time-entries", json={"category": "School", **SESSION}
                         ).json()["result"]["time_entry"]["id"]
    ids = {"ENTRY": climbing, "SCHOOL": school}
    if body.get("time_entry_id") in ids:
        body = {**body, "time_entry_id": ids[body["time_entry_id"]]}
    r = client.post("/climbs", json=body)
    assert r.status_code == status and needle in r.json()["detail"], r.text


def test_deleting_entry_and_undo_brings_climb_back(client, session):
    out = _climb(client, gym="Vital", notes="overhang", **SESSION)
    entry_id = out["result"]["time_entry"]["id"]
    deleted = client.delete(f"/time-entries/{entry_id}").json()
    assert session.scalar(select(Climb)) is None
    _undo(client, deleted["action_id"])
    row = session.scalar(select(Climb))
    assert (row.time_entry_id, row.gym, row.notes) == (entry_id, "Vital", "overhang")


def test_get_climbs_includes_plain_climbing_entries(client):
    _climb(client, gym="Vital", **SESSION)
    client.post("/time-entries", json={"category": "Climbing", "started_at": "2026-11-16T18:00:00",
                                       "ended_at": "2026-11-16T19:00:00"})
    client.post("/time-entries", json={"category": "School", **SESSION})
    rows = client.get("/climbs", params={"start": "2026-11-16", "end": "2026-11-17"}).json()
    assert [(r["gym"], r["time_entry"]["duration_min"]) for r in rows] == [
        ("Vital", 120), (None, 60)]  # newest first; the plain entry has no details


# --- /log ----------------------------------------------------------------------

def test_quickadd_logs_climb_with_gym(client):
    out = client.post("/log", json={"text": "climbed 2-4 at Vital, worked the overhang"}).json()
    assert out["via"] == "quickadd" and out["error"] is None
    assert [a["action_type"] for a in out["actions"]] == ["log_climb"]
    climb = out["actions"][0]["result"]["climb"]
    assert (climb["gym"], climb["notes"]) == ("Vital", "worked the overhang")


def test_ai_adds_details_to_existing_entry(client, fake):  # noqa: F811
    entry_id = _climb(client, **SESSION)["result"]["time_entry"]["id"]
    # The model echoes times alongside the id; they're dropped, not rejected.
    fake([("log_climb", {"time_entry_id": entry_id, "gym": "Vital",
                         "started_at": "2026-11-17T14:00:00", "notes": "first V5"})])
    out = client.post("/log", json={"text": "that climb was at vital, sent my first v5"}).json()
    assert out["error"] is None and out["via"] == "ai", out
    climb = out["actions"][0]["result"]["climb"]
    assert (climb["time_entry_id"], climb["gym"], climb["notes"]) == (entry_id, "Vital", "first V5")


def test_invented_climb_start_becomes_question():
    said_at = to_utc(__import__("datetime").datetime(2026, 11, 17, 17, 30))
    call = ToolCall("log_climb", {"started_at": "2026-11-17T14:09:00",
                                  "ended_at": "2026-11-17T17:00:00"})
    field = find_invented_time(call, "climbed until 5 at vital", said_at)
    assert field == "started_at"
    assert invented_time_question(call, field).question == "What time did you start climbing?"
