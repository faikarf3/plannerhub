"""POST /events: pipeline keys, validation, reactions, retries, undo, the
missing-night check and the digest lines."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.actions import ActionContext
from app.main import app
from app.models import ActionLog, Application, ContentItem, Event, Task
from app.pipelines import check_missing
from app.timeutil import LOCAL_TZ, to_utc

AT = "2026-11-19T03:12:00"  # New York, a typical night run


def _event(client, type_, data, expect=200, **extra):
    body = {"source": extra.pop("source", None), "type": type_, "data": data, **extra}
    body = {k: v for k, v in body.items() if v is not None}
    r = client.post("/events", json=body, **({"headers": extra["headers"]} if "headers" in extra
                                             else {}))
    assert r.status_code == expect, r.text
    return r.json()


def _facts(client, type_, data, **extra):
    return _event(client, type_, data, source="3am_facts", occurred_at=AT, **extra)


def _tracker(client, type_, data, **extra):
    return _event(client, type_, data, source="job_tracker", occurred_at=AT, **extra)


@pytest.fixture
def anon(client):
    return TestClient(app)


def _key(client, source):
    r = client.post("/pipeline-keys", json={"source": source})
    assert r.status_code == 201, r.text
    return r.json()


# --- keys and auth ---------------------------------------------------------------

def test_pipeline_key_posts_for_its_own_source(client, anon):
    out = _key(client, "3am_facts")
    key = out["result"]["key"]
    assert key.startswith("ph_") and out["result"]["pipeline_key"]["hint"] == key[:10]
    assert "key" not in client.get("/pipeline-keys").json()[0]  # only the hint is listed

    auth = {"Authorization": f"Bearer {key}"}
    r = anon.post("/events", headers=auth,
                  json={"type": "video_created", "data": {"title": "Honey never spoils"}})
    assert r.status_code == 200 and r.json()["error"] is None, r.text

    wrong = anon.post("/events", headers=auth, json={"source": "job_tracker",
                                                     "type": "run_finished", "data": {}})
    assert wrong.status_code == 403 and "belongs to 3am_facts" in wrong.json()["message"]
    # A pipeline key is not the owner token: the rest of the API stays closed.
    assert anon.get("/today", headers=auth).status_code == 401


def test_revoked_or_unknown_key_is_refused(client, anon):
    out = _key(client, "job_tracker")
    auth = {"Authorization": f"Bearer {out['result']['key']}"}
    body = {"type": "run_finished", "data": {"count": 3}}
    assert anon.post("/events", headers=auth, json=body).status_code == 200

    revoked = client.delete(f"/pipeline-keys/{out['result']['pipeline_key']['id']}")
    assert revoked.status_code == 200
    r = anon.post("/events", headers=auth, json=body)
    assert r.status_code == 401 and "revoked" in r.json()["message"]

    client.post(f"/actions/{revoked.json()['action_id']}/undo")  # un-revoke
    assert anon.post("/events", headers=auth, json=body).status_code == 200
    assert anon.post("/events", headers={"Authorization": "Bearer nope"},
                     json=body).status_code == 401


def test_unknown_pipeline_key_source(client):
    r = client.post("/pipeline-keys", json={"source": "instagram"})
    assert r.status_code == 422 and "unknown pipeline" in r.json()["message"]


@pytest.mark.parametrize("body, needle", [
    ({"type": "video_created", "data": {"title": "x"}}, "source is required"),
    ({"source": "spotify", "type": "x", "data": {}}, "unknown source"),
    ({"source": "3am_facts", "type": "render_done", "data": {}}, "doesn't send 'render_done'"),
    ({"source": "3am_facts", "type": "video_created", "data": {}}, "bad video_created data: title"),
    ({"source": "job_tracker", "type": "reply_received",
      "data": {"company": "Grab", "kind": "ghosted"}}, "kind"),
])
def test_bad_events_are_refused_and_not_stored(client, session, body, needle):
    r = client.post("/events", json=body)
    assert r.status_code == 422 and needle in r.json()["message"], r.text
    assert session.scalars(select(Event)).all() == []


# --- 3AM Facts -------------------------------------------------------------------

def test_facts_night_created_then_posted(client, session):
    out = _facts(client, "video_created", {"title": "Bananas are berries", "url": "file://v.mp4"})
    assert out["message"] == "3AM Facts Thu Nov 19: created"
    _facts(client, "posted", {"platform": "TikTok", "url": "https://tiktok/1"})
    _facts(client, "posted", {"platform": "instagram", "url": "https://ig/1"})
    # Out of order: a late "created" doesn't undo "posted".
    _facts(client, "video_created", {"title": "Bananas are berries"})

    item = session.scalar(select(ContentItem))
    assert (item.run_date.isoformat(), item.status, item.title) == (
        "2026-11-19", "posted", "Bananas are berries")
    assert item.posts == {"tiktok": "https://tiktok/1", "instagram": "https://ig/1"}
    assert client.get("/content").json()[0]["status"] == "posted"


def test_facts_failure_marks_night_and_adds_task(client, session):
    out = _facts(client, "run_failed", {"step": "render", "error": "ffmpeg exited 1"})
    assert out["error"] is None
    assert [a["action_type"] for a in out["actions"]] == ["save_content_item", "create_task"]
    item = session.scalar(select(ContentItem))
    assert (item.status, item.error) == ("failed", "render: ffmpeg exited 1")

    task = session.scalar(select(Task))
    assert task.title == "Fix 3AM Facts run (render failed)"
    assert (task.linked_type, task.linked_id, task.source) == ("content_item", item.id, "pipeline")
    assert task.due_at.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M") == "2026-11-19 23:59"

    logged = session.scalars(select(ActionLog).order_by(ActionLog.id)).all()
    assert {a.event_id for a in logged} == {out["event_id"]}


def test_retry_with_same_id_is_ignored(client, session):
    first = _facts(client, "video_created", {"title": "A"}, id="run-2026-11-19-created")
    again = _facts(client, "video_created", {"title": "A"}, id="run-2026-11-19-created")
    assert again["duplicate"] is True and again["event_id"] == first["event_id"]
    assert again["actions"] == [] and "ignored" in again["message"]
    assert len(session.scalars(select(Event)).all()) == 1


# --- job tracker -----------------------------------------------------------------

def test_applications_and_replies(client, session):
    _tracker(client, "application_submitted",
             {"company": "Traveloka", "role": "Software Engineer Intern", "url": "https://t/1"})
    _tracker(client, "application_submitted", {"company": "Grab", "role": "Backend Engineer"})

    out = _tracker(client, "reply_received", {
        "company": "traveloka", "kind": "interview", "deadline": "2026-11-23T10:00:00"})
    assert [a["action_type"] for a in out["actions"]] == ["save_application", "create_task"]
    assert out["actions"][0]["summary"] == "Traveloka (Software Engineer Intern): now interview"
    task = session.scalar(select(Task))
    assert task.title == "Traveloka: interview" and task.linked_type == "application"
    assert task.due_at == to_utc(datetime(2026, 11, 23, 10))

    rejected = _tracker(client, "reply_received", {"company": "Grab", "kind": "rejection"})
    assert [a["action_type"] for a in rejected["actions"]] == ["save_application"]

    statuses = {a["company"]: a["status"] for a in client.get("/applications").json()}
    assert statuses == {"Traveloka": "interview", "Grab": "rejected"}
    assert [a["company"] for a in client.get("/applications?status=rejected").json()] == ["Grab"]


def test_reply_for_unknown_company_creates_it(client):
    out = _tracker(client, "reply_received", {"company": "Shopee", "kind": "oa"})
    app_ = out["actions"][0]["result"]["application"]
    assert (app_["company"], app_["status"]) == ("Shopee", "oa")
    assert out["actions"][1]["result"]["task"]["title"] == "Shopee: online assessment"


def test_same_company_different_role_is_a_new_application(client, session):
    _tracker(client, "application_submitted", {"company": "Gojek", "role": "Platform Engineer"})
    _tracker(client, "application_submitted", {"company": "Gojek", "role": "Data Engineer"})
    _tracker(client, "application_submitted", {"company": "GOJEK", "role": "data engineer"})
    assert len(session.scalars(select(Application)).all()) == 2


def test_undo_an_event_reaction(client, session):
    out = _tracker(client, "application_submitted", {"company": "Agoda", "role": "SWE"})
    r = client.post(f"/actions/{out['actions'][0]['action_id']}/undo")
    assert r.status_code == 200 and r.json()["event_id"] == out["event_id"]
    assert session.scalars(select(Application)).all() == []
    assert session.get(Event, out["event_id"]) is not None  # the raw event stays


def test_heartbeat_and_tracker_failure(client, session):
    beat = _tracker(client, "run_finished", {"count": 14})
    assert beat["actions"] == [] and beat["message"] == "recorded"
    fail = _tracker(client, "run_failed", {"error": "login expired"})
    assert fail["actions"][0]["result"]["task"]["title"] == "Fix job tracker run"
    events = client.get("/events?source=job_tracker").json()
    assert [e["type"] for e in events] == ["run_failed", "run_finished"]


# --- missing night and digest ----------------------------------------------------

def _ctx(session, local: datetime) -> ActionContext:
    return ActionContext(session=session, now=to_utc(local))


def test_missing_night_is_flagged_once(session):
    assert check_missing(_ctx(session, datetime(2026, 11, 19, 6, 30))) == []  # too early
    flagged = check_missing(_ctx(session, datetime(2026, 11, 19, 7, 5)))
    assert [a.action_type for a in flagged] == ["save_content_item", "create_task"]
    assert session.scalar(select(ContentItem)).status == "missing"
    assert check_missing(_ctx(session, datetime(2026, 11, 19, 8))) == []  # already flagged


def test_reported_night_is_not_missing(client, session):
    _facts(client, "video_created", {"title": "On time"})
    assert check_missing(_ctx(session, datetime(2026, 11, 19, 9))) == []


def test_digest_lines(client):
    plain = client.get("/digest/morning", params={"day": "2026-11-19"}).json()
    assert "3AM Facts" not in plain["text"] and "Applications" not in plain["text"]

    _facts(client, "video_created", {"title": "Bananas are berries"})
    _facts(client, "posted", {"platform": "tiktok"})
    for company in ("A", "B", "C"):
        _event(client, "application_submitted", {"company": company}, source="job_tracker",
               occurred_at="2026-11-18T15:00:00")
    digest = client.get("/digest/morning", params={"day": "2026-11-19"}).json()
    assert "3AM Facts: “Bananas are berries” is up (tiktok)" in digest["text"]
    assert "Applications yesterday: 3/20" in digest["text"]
    assert digest["applications_yesterday"] == 3
    assert digest["facts_last_night"]["status"] == "posted"
