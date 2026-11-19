"""SI weekly plan. Clock frozen at Wed 2026-11-18 12:00 New York, so the current
week is Monday 2026-11-23 and prep counts from Mon 11-16 up to Mon 11-23."""

from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.models import SiSession
from app.si import current_week_of
from app.timeutil import LOCAL_TZ

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=LOCAL_TZ)
WEEK = "2026-11-23"


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr("app.routers.si.utcnow", lambda: NOW)


def _rows(session):
    return session.scalar(select(func.count()).select_from(SiSession))


def _current(client):
    r = client.get("/si-sessions/current")
    assert r.status_code == 200, r.text
    return r.json()


def _patch(client, body, week=WEEK, expect=200):
    r = client.patch(f"/si-sessions/{week}", json=body)
    assert r.status_code == expect, r.text
    return r.json()


@pytest.mark.parametrize("today, monday", [
    (date(2026, 11, 23), date(2026, 11, 23)),  # Monday: this one
    (date(2026, 11, 24), date(2026, 11, 30)),  # Tuesday: next
    (date(2026, 11, 29), date(2026, 11, 30)),  # Sunday: tomorrow
])
def test_current_week_of(today, monday):
    assert current_week_of(today) == monday


def test_no_row_returns_defaults_without_writing(client, session):
    week = _current(client)
    assert week == {
        "id": None, "week_of": WEEK, "topic": None, "plan_form_done": False,
        "slides_done": False, "breakdown_done": False, "answer_sheet_done": False,
        "session_at": None, "attendance": None, "prep_minutes_this_week": 0,
    }
    assert _rows(session) == 0


def test_first_save_creates_row_and_undo_removes_it(client, session):
    out = _patch(client, {"topic": "  Rotational motion ", "slides_done": True,
                          "session_at": "2026-11-23T10:00:00"})
    assert out["action_type"] == "update_si_session"
    saved = out["result"]["si_session"]
    assert saved["topic"] == "Rotational motion" and saved["slides_done"] is True
    assert saved["session_at"] == "2026-11-23T15:00:00Z"  # 10am EST
    assert "slides done" in out["summary"]
    assert _current(client)["id"] == saved["id"]

    assert client.post(f"/actions/{out['action_id']}/undo").status_code == 200
    assert _current(client)["id"] is None
    assert _rows(session) == 0


def test_later_save_and_undo_restores_previous_values(client):
    _patch(client, {"topic": "Torque", "plan_form_done": True})
    before = _current(client)
    out = _patch(client, {"topic": None, "plan_form_done": False, "attendance": 14})
    after = _current(client)
    assert after["topic"] is None and after["plan_form_done"] is False
    assert after["attendance"] == 14

    client.post(f"/actions/{out['action_id']}/undo")
    assert _current(client) == before


def test_other_weeks_can_be_set_directly(client):
    out = _patch(client, {"breakdown_done": True}, week="2026-12-07")
    assert out["result"]["si_session"]["week_of"] == "2026-12-07"
    assert _current(client)["breakdown_done"] is False  # current week untouched


@pytest.mark.parametrize("week, body, needle", [
    ("2026-11-24", {"topic": "x"}, "must be a Monday; 2026-11-24 is a Tuesday"),
    (WEEK, {}, "at least one field"),
    (WEEK, {"slides_done": None}, "slides_done must be true or false"),
    (WEEK, {"attendance": -1}, "attendance"),
])
def test_rejections(client, week, body, needle):
    out = _patch(client, body, week=week, expect=422)
    assert needle in out["message"]


def test_prep_minutes_this_week(client):
    def log(**body):
        r = client.post("/time-entries", json={"category": "SI Prep", "job": "si_prep", **body})
        assert r.status_code == 201, r.text

    log(started_at="2026-11-17T18:00:00", ended_at="2026-11-17T19:00:00")   # in: 60
    log(started_at="2026-11-16T00:00:00", ended_at="2026-11-16T00:15:00")   # in (window start): 15
    log(started_at="2026-11-15T20:00:00", ended_at="2026-11-15T20:30:00")   # before window
    log(started_at="2026-11-23T08:00:00", ended_at="2026-11-23T08:45:00")   # on the Monday: out
    client.post("/time-entries", json={"category": "Work", "job": "tutoring",
                                       "started_at": "2026-11-17T15:00:00",
                                       "ended_at": "2026-11-17T18:00:00"})  # not prep
    # Running prep timer since 11:00 counts up to "now" (12:00): 60.
    r = client.post("/timer/start", json={"category": "SI Prep", "job": "si_prep",
                                          "at": "2026-11-18T11:00:00"})
    assert r.status_code == 200, r.text

    assert _current(client)["prep_minutes_this_week"] == 60 + 15 + 60
