"""Repeating schedules: rules, expansion (overnight, DST, until), one-week
skip/move/confirm with undo, /calendar, and Today/digest."""

import pytest
from sqlalchemy import select

from app.models import Schedule, ScheduleException, TimeEntry

TUTORING = {"job": "tutoring", "weekdays": [1], "start_time": "15:00", "end_time": "18:00",
            "starts_on": "2026-10-01"}
RESTAURANT = {"job": "restaurant", "weekdays": [5, 6], "start_time": "17:00",
              "end_time": "01:00", "starts_on": "2026-10-01"}


def _create(client, body, expect=201):
    r = client.post("/schedules", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def _undo(client, action_id):
    r = client.post(f"/actions/{action_id}/undo")
    assert r.status_code == 200, r.text


def _planned(client, start, end=None, **params):
    params = {"start": start, **({"end": end} if end else {}), **params}
    return client.get("/calendar", params=params).json()["planned"]


def _occ(client, sid, on_date, verb, expect=200, **body):
    r = client.post(f"/schedules/{sid}/occurrences/{on_date}/{verb}", json=body or None)
    assert r.status_code == expect, r.text
    return r.json()


# --- rules -----------------------------------------------------------------------

def test_create_and_list(client):
    out = _create(client, TUTORING)
    assert out["summary"] == "Added repeat: Tutoring, Tue 3:00pm–6:00pm"
    assert out["result"]["schedule"]["category_id"]  # Work, from the job
    _create(client, RESTAURANT)
    _create(client, {"category": "School", "weekdays": [1, 3], "start_time": "10:00",
                     "end_time": "12:00", "title": "PH201"})

    listed = client.get("/schedules").json()
    by_label = {s["label"]: s for s in listed["schedules"]}
    assert by_label["Tutoring"]["minutes_per_week"] == 180
    assert by_label["Restaurant"]["minutes_per_week"] == 960  # 2 overnight shifts of 8h
    assert by_label["Restaurant"]["description"] == "Sat, Sun 5:00pm–1:00am"
    assert by_label["PH201"]["is_work"] is False
    assert listed["paid_minutes_per_week"] == 180 + 960


@pytest.mark.parametrize("body, needle", [
    ({**TUTORING, "weekdays": [7]}, "0 (Monday) to 6"),
    ({**TUTORING, "weekdays": []}, "weekdays"),
    ({**TUTORING, "end_time": "15:00"}, "can't be the same"),
    ({**TUTORING, "until": "2026-09-01"}, "until can't be before"),
    ({"category": "Work", "weekdays": [1], "start_time": "09:00", "end_time": "10:00"},
     "job is required"),
    ({**TUTORING, "job": "dishwashing"}, "unknown job"),
])
def test_create_rejections(client, body, needle):
    r = client.post("/schedules", json=body)
    assert r.status_code == 422 and needle in r.json()["message"], r.text


def test_update_and_undo(client):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    r = client.patch(f"/schedules/{sid}", json={"weekdays": [3, 1], "end_time": "17:00"})
    assert r.json()["summary"] == "Updated repeat: Tutoring, Tue, Thu 3:00pm–5:00pm"
    bad = client.patch(f"/schedules/{sid}", json={"end_time": "15:00"})
    assert bad.status_code == 422
    _undo(client, r.json()["action_id"])
    s = client.get("/schedules").json()["schedules"][0]
    assert (s["weekdays"], s["end_time"]) == ([1], "18:00:00")


def test_delete_and_undo_keeps_exceptions(client, session):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    _occ(client, sid, "2026-11-24", "skip")
    deleted = client.delete(f"/schedules/{sid}").json()
    assert session.scalars(select(ScheduleException)).all() == []
    _undo(client, deleted["action_id"])
    assert session.get(Schedule, sid) is not None
    assert session.scalar(select(ScheduleException)).skipped is True


# --- expansion -------------------------------------------------------------------

def test_calendar_week_with_overnight_shifts(client):
    _create(client, TUTORING)
    _create(client, RESTAURANT)
    planned = _planned(client, "2026-11-16")  # Mon..Sun
    got = [(p["label"], p["on_date"], p["started_at"], p["ended_at"]) for p in planned]
    assert got == [
        # Last Sunday's shift runs into Monday 1am, so it shows in this week too.
        ("Restaurant", "2026-11-15", "2026-11-15T22:00:00Z", "2026-11-16T06:00:00Z"),
        ("Tutoring", "2026-11-17", "2026-11-17T20:00:00Z", "2026-11-17T23:00:00Z"),
        ("Restaurant", "2026-11-21", "2026-11-21T22:00:00Z", "2026-11-22T06:00:00Z"),
        ("Restaurant", "2026-11-22", "2026-11-22T22:00:00Z", "2026-11-23T06:00:00Z"),
    ]
    assert all(p["status"] == "planned" and p["is_work"] for p in planned)


def test_wall_clock_holds_across_dst(client):
    _create(client, TUTORING)  # DST ends Sun Nov 1, 2026
    before = _planned(client, "2026-10-27", "2026-10-27")[0]["started_at"]
    after = _planned(client, "2026-11-03", "2026-11-03")[0]["started_at"]
    assert (before, after) == ("2026-10-27T19:00:00Z", "2026-11-03T20:00:00Z")  # both 3pm


def test_starts_on_and_until(client):
    _create(client, {**TUTORING, "starts_on": "2026-11-03", "until": "2026-11-17"})
    days = [p["on_date"] for p in _planned(client, "2026-10-26", "2026-12-06")]
    assert days == ["2026-11-03", "2026-11-10", "2026-11-17"]
    s = client.get("/schedules").json()
    assert s["schedules"][0]["active"] is False and s["paid_minutes_per_week"] == 0


# --- one week --------------------------------------------------------------------

def test_skip_one_week_and_undo(client):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    out = _occ(client, sid, "2026-11-24", "skip")
    assert out["summary"] == "Skipped Tutoring on Tue Nov 24"
    assert _planned(client, "2026-11-23") == []
    shown = _planned(client, "2026-11-23", include_skipped=True)
    assert [p["status"] for p in shown] == ["skipped"]
    assert len(_planned(client, "2026-11-30")) == 1  # the rule is untouched

    _occ(client, sid, "2026-11-24", "skip", expect=409)
    _occ(client, sid, "2026-11-25", "skip", expect=422)  # a Wednesday: no occurrence
    _undo(client, out["action_id"])
    assert [p["status"] for p in _planned(client, "2026-11-23")] == ["planned"]


def test_move_one_week_and_undo(client):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    out = _occ(client, sid, "2026-11-24", "move",
               started_at="2026-11-24T16:00:00", ended_at="2026-11-24T19:00:00")
    p = _planned(client, "2026-11-23")[0]
    assert (p["started_at"], p["moved"]) == ("2026-11-24T21:00:00Z", True)
    _undo(client, out["action_id"])
    p = _planned(client, "2026-11-23")[0]
    assert (p["started_at"], p["moved"]) == ("2026-11-24T20:00:00Z", False)


def test_confirm_logs_time_and_undo(client, session):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    out = _occ(client, sid, "2026-11-10", "confirm")
    entry = out["result"]["time_entry"]
    assert (entry["job"], entry["duration_min"], entry["source"]) == ("tutoring", 180, "calendar")
    p = _planned(client, "2026-11-09")[0]
    assert (p["status"], p["time_entry_id"]) == ("done", entry["id"])

    _occ(client, sid, "2026-11-10", "confirm", expect=409)
    _occ(client, sid, "2026-11-10", "skip", expect=409)
    _undo(client, out["action_id"])
    assert session.get(TimeEntry, entry["id"]) is None
    assert _planned(client, "2026-11-09")[0]["status"] == "planned"


def test_confirm_with_actual_times_after_a_move(client):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    _occ(client, sid, "2026-11-10", "move",
         started_at="2026-11-10T16:00:00", ended_at="2026-11-10T19:00:00")
    out = _occ(client, sid, "2026-11-10", "confirm", ended_at="2026-11-10T18:30:00")
    assert out["result"]["time_entry"]["duration_min"] == 150  # moved start, given end


def test_cannot_confirm_the_future(client):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    r = client.post(f"/schedules/{sid}/occurrences/2027-03-02/confirm")
    assert r.status_code == 422 and "hasn't started yet" in r.json()["message"]


def test_deleting_the_entry_makes_it_planned_again(client):
    sid = _create(client, TUTORING)["result"]["schedule"]["id"]
    entry = _occ(client, sid, "2026-11-10", "confirm")["result"]["time_entry"]
    client.delete(f"/time-entries/{entry['id']}")
    assert _planned(client, "2026-11-09")[0]["status"] == "planned"


# --- calendar, today, digest -----------------------------------------------------

def test_calendar_has_entries_and_tasks(client):
    client.post("/time-entries", json={"category": "Climbing", "started_at": "2026-11-17T14:00:00",
                                       "ended_at": "2026-11-17T16:00:00"})
    client.post("/tasks", json={"title": "Study group", "category": "School",
                                "scheduled_start": "2026-11-18T19:00:00",
                                "scheduled_end": "2026-11-18T20:00:00"})
    cal = client.get("/calendar", params={"start": "2026-11-16"}).json()
    assert (cal["start"], cal["end"]) == ("2026-11-16", "2026-11-22")
    assert [e["duration_min"] for e in cal["entries"]] == [120]
    assert [t["title"] for t in cal["tasks"]] == ["Study group"]


def test_today_and_digest_include_repeats(client):
    _create(client, TUTORING)
    today = client.get("/today", params={"day": "2026-11-24"}).json()
    assert [b["label"] for b in today["planned_blocks"]] == ["Tutoring"]
    digest = client.get("/digest/morning", params={"day": "2026-11-24"}).json()
    assert "Shifts: Tutoring" in digest["text"]
    assert [b["label"] for b in digest["planned_blocks"]] == ["Tutoring"]
