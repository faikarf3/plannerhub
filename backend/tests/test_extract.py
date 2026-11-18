"""AI fallback for /log and the clarify round-trip, with a fake extractor."""

import re

import pytest

from app.actions import REGISTRY
from app.extract import (
    TOOLS,
    Extraction,
    ExtractionError,
    build_prompt,
    get_extractor,
    to_extraction,
)
from app.main import app
from app.models import ActionLog, JournalEntry
from app.timeutil import to_utc


class FakeExtractor:
    """Returns queued raw tool calls (as the provider would) and records prompts."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def extract(self, system, prompt, tools):
        self.prompts.append(prompt)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return to_extraction(nxt)


@pytest.fixture
def fake(client):
    holder = {}

    def use(*responses):
        holder["x"] = FakeExtractor(*responses)
        app.dependency_overrides[get_extractor] = lambda: holder["x"]
        return holder["x"]

    return use


def _log(client, text, **extra):
    r = client.post("/log", json={"text": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# --- tool definitions --------------------------------------------------------

def _check_fields(props, model):
    for name, spec in props.items():
        assert name in model.model_fields, f"{model.__name__} has no field {name}"
        if spec.get("type") == "object":
            _check_fields(spec["properties"], model.model_fields[name].annotation)


@pytest.mark.parametrize("tool", [t for t in TOOLS if t["name"] != "clarify"],
                         ids=lambda t: t["name"])
def test_tool_fields_exist_on_action(tool):
    defn = REGISTRY[tool["name"]]
    assert not defn.internal
    _check_fields(tool["parameters"]["properties"], defn.params)


def test_to_extraction_filters_and_clarify_wins():
    ex = to_extraction([
        ("log_time", {"category": "Climbing", "duration_min": 60, "source": "pipeline",
                      "note": None}),
        ("delete_task", {"task_id": 1}),
        ("update_task", {"task_id": 3, "fields": {"title": "x", "due_at": None, "linked_id": 9}}),
    ])
    assert ex.clarify is None
    assert [(c.name, c.args) for c in ex.calls] == [
        ("log_time", {"category": "Climbing", "duration_min": 60}),
        ("update_task", {"task_id": 3, "fields": {"title": "x"}}),
    ]
    ex = to_extraction([("create_task", {"title": "a"}),
                        ("clarify", {"question": "Which day?", "options": ["fri", "sat"]})])
    assert ex.calls == [] and ex.clarify.question == "Which day?"
    assert ex.clarify.options == ["fri", "sat"]


def test_normalize_job_category_and_redundant_duration():
    ex = to_extraction([
        ("log_time", {"job": "tutoring", "started_at": "2026-11-17T09:00:00",
                      "ended_at": "2026-11-17T10:00:00", "duration_min": 60}),
        ("start_timer", {"job": "si_prep"}),
        ("log_time", {"category": "SI Prep (work)", "duration_min": 45}),
    ])
    assert ex.calls[0].args == {"job": "tutoring", "category": "Work",
                                "started_at": "2026-11-17T09:00:00",
                                "ended_at": "2026-11-17T10:00:00"}
    assert ex.calls[1].args == {"job": "si_prep", "category": "SI Prep"}
    assert ex.calls[2].args["category"] == "SI Prep"


def test_prompt_has_context(client, session):
    client.post("/tasks", json={"title": "Follow up Traveloka", "category": "Job Search"})
    client.post("/timer/start", json={"category": "Climbing"})
    prompt = build_prompt(session, to_utc(__import__("datetime").datetime(2026, 11, 17, 14)),
                          "did the thing")
    assert "now: Tue 2026-11-17 14:00" in prompt
    assert "Follow up Traveloka [Job Search]" in prompt
    assert re.search(r"running_timer: #\d+ Climbing since", prompt)
    assert prompt.endswith("log:\ndid the thing")


# --- /log fallback -----------------------------------------------------------

def test_quickadd_does_not_call_extractor(client, fake):
    x = fake()
    out = _log(client, "climb 2h vital")
    assert out["via"] == "quickadd" and x.prompts == []


def test_ai_applies_actions_with_journal_link(client, session, fake):
    fake([("log_time", {"category": "Climbing", "started_at": "2026-11-17T14:00:00",
                        "ended_at": "2026-11-17T16:00:00", "note": "vital"}),
          ("create_task", {"title": "Buy chalk"})])
    out = _log(client, "went climbing at vital from 2 to 4, need to buy chalk")
    assert out["parsed"] is True and out["via"] == "ai" and out["error"] is None
    assert [a["action_type"] for a in out["actions"]] == ["log_time", "create_task"]
    assert out["actions"][0]["result"]["time_entry"]["duration_min"] == 120
    for a in out["actions"]:
        assert session.get(ActionLog, a["action_id"]).journal_entry_id == out["journal_entry_id"]
    # each AI action is individually undoable
    undo = client.post(f"/actions/{out['actions'][1]['action_id']}/undo")
    assert undo.status_code == 200


def test_ai_nothing_actionable(client, session, fake):
    fake([])
    out = _log(client, "honestly kind of a rough day")
    assert out["parsed"] is False and out["via"] == "ai" and out["actions"] == []
    assert session.get(JournalEntry, out["journal_entry_id"]).raw_text.startswith("honestly")


def test_ai_unavailable_keeps_journal(client, session, fake):
    fake(ExtractionError("429 quota exceeded"))
    out = _log(client, "something unparseable here")
    assert out["parsed"] is False and "AI unavailable" in out["error"]
    assert session.get(JournalEntry, out["journal_entry_id"]) is not None


def test_ai_invalid_action_reports_error(client, fake):
    fake([("log_time", {"category": "Nope", "duration_min": 30})])
    out = _log(client, "spent half an hour on nope stuff")
    assert out["actions"] == [] and "unknown category" in out["error"]


def test_ai_timer_uses_recording_time(client, fake):
    fake([("start_timer", {"category": "Climbing"})])
    _log(client, "heading into the gym now", at="2026-11-17T09:30:00")
    assert client.get("/timer").json()["started_at"].startswith("2026-11-17T14:30")


# --- clarify -----------------------------------------------------------------

def test_clarify_round_trip(client, session, fake):
    x = fake([("clarify", {"question": "What time did you start?", "options": ["2pm", "3pm"]})],
             [("log_time", {"category": "Climbing", "started_at": "2026-11-17T14:00:00",
                            "ended_at": "2026-11-17T16:00:00"})])
    out = _log(client, "climbed until 4")
    assert out["actions"] == [] and out["clarify"]["options"] == ["2pm", "3pm"]
    assert out["message"] == "What time did you start?"
    jid = out["journal_entry_id"]

    r = client.post(f"/clarify/{jid}", json={"answer": "2pm"})
    assert r.status_code == 200, r.text
    out2 = r.json()
    assert out2["journal_entry_id"] == jid and out2["clarify"] is None
    assert out2["actions"][0]["result"]["time_entry"]["duration_min"] == 120
    assert "You asked: What time did you start?\nAnswer: 2pm" in x.prompts[1]
    assert session.get(JournalEntry, jid).clarify_answer == "2pm"

    again = client.post(f"/clarify/{jid}", json={"answer": "3pm"})
    assert again.status_code == 409


def test_clarify_without_question(client, fake):
    fake([("create_task", {"title": "x"})])
    out = _log(client, "remind me about the thing")
    jid = out["journal_entry_id"]
    assert client.post(f"/clarify/{jid}", json={"answer": "y"}).status_code == 409
    assert client.post("/clarify/999999", json={"answer": "y"}).status_code == 404


def test_fallback_off_without_key(client):
    out = _log(client, "honestly kind of a rough day")
    assert out["parsed"] is False and out["via"] is None


def test_extraction_type_default():
    assert Extraction().calls == [] and Extraction().clarify is None


# --- set_mood and request logging ---------------------------------------------

def test_ai_set_mood_on_this_entry_and_undo(client, session, fake):
    fake([("set_mood", {"mood": 2, "energy": 1, "journal_entry_id": 999})])
    out = _log(client, "rough day, pretty exhausted")
    jid = out["journal_entry_id"]
    assert out["actions"][0]["summary"] == "Noted mood 2/5, energy 1/5"
    entry = session.get(JournalEntry, jid)
    assert (entry.mood, entry.energy) == (2, 1)  # injected id wins over the model's

    assert client.post(f"/actions/{out['actions'][0]['action_id']}/undo").status_code == 200
    session.refresh(entry)
    assert (entry.mood, entry.energy) == (None, None)


def test_set_mood_validation(client, fake):
    fake([("set_mood", {"mood": 9})])
    out = _log(client, "feeling incredible")
    assert out["actions"] == [] and "invalid set_mood" in out["error"]
    fake([("set_mood", {})])
    out = _log(client, "meh")
    assert "needs mood or energy" in out["error"]


def test_request_log_line_has_no_user_text(client, fake, caplog):
    fake([("create_task", {"title": "Buy chalk"})])
    with caplog.at_level("INFO", logger="planner.log"):
        out = _log(client, "secret diary words, buy chalk")
    line = caplog.records[-1].getMessage()
    assert f"log journal={out['journal_entry_id']} via=ai parsed=True" in line
    assert "create_task#" in line and "secret" not in line and "chalk" not in line


# --- invented-time guard ------------------------------------------------------

def _guard(name, args, text, said="2026-11-17T20:10:30"):
    from app.extract import ToolCall, find_invented_time
    return find_invented_time(ToolCall(name, args), text, to_utc(
        __import__("datetime").datetime.fromisoformat(said)))


@pytest.mark.parametrize(("name", "args", "text", "bad"), [
    # the observed failure: start made up for "until 5"
    ("log_time", {"started_at": "2026-11-17T14:09:00", "ended_at": "2026-11-17T17:00:00"},
     "climbed until 5, felt amazing", "started_at"),
    ("log_time", {"started_at": "2026-11-17T14:00:00", "ended_at": "2026-11-17T16:00:00"},
     "went climbing from 2 to 4", None),
    ("log_time", {"started_at": "2026-11-17T09:00:00", "ended_at": "2026-11-17T12:00:00"},
     "tutored this morning", "started_at"),
    ("log_time", {"started_at": "2026-11-17T15:00:00", "ended_at": "2026-11-17T18:00:00"},
     "tutoring three to six", None),
    ("log_time", {"started_at": "2026-11-17T12:00:00", "ended_at": "2026-11-17T13:30:00"},
     "lunch study from noon till 1:30", None),
    # duration only, or ending at the moment it was said
    ("log_time", {"duration_min": 120}, "did 2 hours of homework", None),
    ("log_time", {"ended_at": "2026-11-17T20:10:00", "duration_min": 45},
     "just finished 45 min of SI prep", None),
    ("log_time", {"started_at": "2026-11-17T19:25:00", "ended_at": "2026-11-17T20:10:00",
                  "duration_min": 45}, "just finished 45 min of SI prep", None),
    # what the model actually sends for these: both ends, no duration field
    ("log_time", {"started_at": "2026-11-17T18:10:00", "ended_at": "2026-11-17T20:10:00"},
     "kind of stressed but did 2 hours of homework", None),
    ("log_time", {"started_at": "2026-11-17T19:25:00", "ended_at": "2026-11-17T20:10:00"},
     "just finished 45 minutes of SI prep", None),
    ("log_time", {"started_at": "2026-11-17T19:10:00", "ended_at": "2026-11-17T20:10:00"},
     "an hour of applications", None),
    ("log_time", {"started_at": "2026-11-17T18:10:00", "ended_at": "2026-11-17T20:10:00"},
     "did 3 hours of homework", "started_at"),  # duration doesn't match what was said
    ("stop_timer", {"at": "2026-11-17T17:00:00"}, "done climbing at 5", None),
    ("stop_timer", {"at": "2026-11-17T17:00:00"}, "done climbing", "at"),
    ("create_task", {"title": "x", "due_at": "2026-11-19T23:59:00"}, "x by thursday", None),
])
def test_invented_time_guard(name, args, text, bad):
    assert _guard(name, args, text) == bad


def test_invented_time_becomes_question_then_answer_backs_it(client, fake):
    fake([("log_time", {"category": "Climbing", "started_at": "2026-11-17T14:09:00",
                        "ended_at": "2026-11-17T17:00:00"})],
         [("log_time", {"category": "Climbing", "started_at": "2026-11-17T14:30:00",
                        "ended_at": "2026-11-17T17:00:00"})])
    out = _log(client, "climbed until 5", at="2026-11-17T20:10:00")
    assert out["actions"] == [] and out["message"] == "What time did you start climbing?"
    r = client.post(f"/clarify/{out['journal_entry_id']}", json={"answer": "2:30"})
    assert r.json()["actions"][0]["result"]["time_entry"]["duration_min"] == 150
