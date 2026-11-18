"""Pure parser tests. Reference time: Tue 2026-11-17 2:30pm New York."""

from datetime import datetime

import pytest

from app.quickadd import parse
from app.timeutil import LOCAL_TZ

NOW = datetime(2026, 11, 17, 14, 30, tzinfo=LOCAL_TZ)
CATS = ["Work", "SI Prep", "Job Search", "Climbing", "3AM Facts", "School", "Personal"]


def ny(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=LOCAL_TZ)


def one(text):
    intents = parse(text, NOW, CATS)
    assert intents is not None, f"not parsed: {text!r}"
    assert len(intents) == 1
    return intents[0].kind, intents[0].payload


# ------------------------------------------------------------ time logs

@pytest.mark.parametrize("text, expected", [
    ("climb 2h vital", {"category": "Climbing", "duration_min": 120, "ended_at": NOW,
                        "note": "vital"}),
    ("SI prep 45m", {"category": "SI Prep", "job": "si_prep", "duration_min": 45,
                     "ended_at": NOW}),
    ("climbing 1.5h", {"category": "Climbing", "duration_min": 90, "ended_at": NOW}),
    ("school 2h30m midterm review", {"category": "School", "duration_min": 150,
                                     "ended_at": NOW, "note": "midterm review"}),
    ("job search 90 min", {"category": "Job Search", "duration_min": 90, "ended_at": NOW}),
    ("3am facts 20m editing", {"category": "3AM Facts", "duration_min": 20, "ended_at": NOW,
                               "note": "editing"}),
])
def test_durations(text, expected):
    assert one(text) == ("log_time", expected)


@pytest.mark.parametrize("text, start, end", [
    ("tutoring 3-6pm", ny(17, 15), ny(17, 18)),
    ("tutoring 3pm-6pm", ny(17, 15), ny(17, 18)),
    ("tutoring 11-1pm", ny(17, 11), ny(17, 13)),
    ("tutoring 10am-12", ny(17, 10), ny(17, 12)),
    ("tutoring from 2 to 4", ny(17, 14), ny(17, 16)),
    ("tutoring 2:30-4", ny(17, 14, 30), ny(17, 16)),
    ("tutoring 14:00-16:15", ny(17, 14), ny(17, 16, 15)),
    ("tutoring 9-11", ny(17, 9), ny(17, 11)),
])
def test_ranges(text, start, end):
    kind, p = one(text)
    assert kind == "log_time"
    assert (p["started_at"], p["ended_at"]) == (start, end)
    assert p["job"] == "tutoring" and p["category"] == "Work"


def test_restaurant_overnight():
    _, p = one("restaurant 6pm-1am")
    assert (p["started_at"], p["ended_at"]) == (ny(17, 18), ny(18, 1))


def test_range_yesterday_with_note():
    _, p = one("climbed 2-4 yesterday at Vital")
    assert (p["started_at"], p["ended_at"]) == (ny(16, 14), ny(16, 16))
    assert p["note"] == "at Vital"
    assert "confirmed" not in p


@pytest.mark.parametrize("text", ["applications about 1h", "applications ~1h",
                                  "job search around 45m", "school approximately 2h"])
def test_estimates_are_unconfirmed(text):
    _, p = one(text)
    assert p["confirmed"] is False
    assert "note" not in p


def test_duration_yesterday_is_estimate():
    _, p = one("climb 2h yesterday")
    assert p["confirmed"] is False
    assert p["ended_at"] == ny(16, 21)


def test_note_keeps_original_case():
    _, p = one("climb 2h Brooklyn Boulders")
    assert p["note"] == "Brooklyn Boulders"


def test_new_category_by_name():
    intents = parse("guitar 30m", NOW, [*CATS, "Guitar"])
    assert intents[0].payload["category"] == "Guitar"


# ------------------------------------------------------------ tasks

@pytest.mark.parametrize("text, title, due", [
    ("task follow up Traveloka fri", "follow up Traveloka", ny(20, 23, 59)),
    ("task call mom tomorrow 5pm", "call mom", ny(18, 17)),
    ("todo submit OA by thursday", "submit OA", ny(19, 23, 59)),
    ("task PH201 slides tonight", "PH201 slides", ny(17, 21)),
    ("task pay rent 12/1", "pay rent", datetime(2026, 12, 1, 23, 59, tzinfo=LOCAL_TZ)),
    ("task dentist on tue at 9:30am", "dentist", ny(17, 9, 30)),  # today counts
    ("task email prof 5pm", "email prof", ny(17, 17)),
])
def test_tasks_with_due(text, title, due):
    kind, p = one(text)
    assert kind == "create_task"
    assert p["title"] == title and p["due_at"] == due


def test_task_no_due_and_hashtag_category():
    assert one("task buy chalk") == ("create_task", {"title": "buy chalk"})
    _, p = one("task follow up Traveloka #job-search fri")
    assert p == {"title": "follow up Traveloka", "category": "Job Search", "due_at": ny(20, 23, 59)}


def test_task_title_ending_in_weekday_word_only():
    # A title that is only a day word isn't stripped to empty.
    assert one("task friday") == ("create_task", {"title": "friday"})


# ------------------------------------------------------------ timers / shifts

@pytest.mark.parametrize("text, expected", [
    ("start climbing", ("start_timer", {"category": "Climbing"})),
    ("starting SI prep", ("start_timer", {"category": "SI Prep", "job": "si_prep"})),
    ("start school at 2pm", ("start_timer", {"category": "School", "at": ny(17, 14)})),
    ("start school PH201 pset", ("start_timer", {"category": "School", "note": "ph201 pset"})),
    ("stop", ("stop_timer", {})),
    ("done", ("stop_timer", {})),
    ("stop at 5", ("stop_timer", {"at": ny(17, 17)})),
    ("clock in tutoring", ("start_timer", {"category": "Work", "job": "tutoring"})),
    ("clocking in for tutoring", ("start_timer", {"category": "Work", "job": "tutoring"})),
    ("clocked in restaurant at 5pm",
     ("start_timer", {"category": "Work", "job": "restaurant", "at": ny(17, 17)})),
    ("clock out", ("stop_timer", {"require_work": True})),
    ("off work", ("stop_timer", {"require_work": True})),
])
def test_timers(text, expected):
    assert one(text) == expected


def test_done_task_vs_done_log():
    assert one("done SI slides") == ("complete_task_by_title", {"query": "SI slides"})
    kind, p = one("done climbing 2h")
    assert kind == "log_time" and p["duration_min"] == 120


@pytest.mark.parametrize("text", [
    "", "had a weird day honestly", "climbing", "clock in", "clock in climbing",
    "start something random", "tutoring 25-26",
])
def test_not_understood(text):
    assert parse(text, NOW, CATS) is None


@pytest.mark.parametrize("text, expected", [
    ("stop climbing", {"category": "Climbing"}),
    ("stopped climbing", {"category": "Climbing"}),
    ("done climbing", {"category": "Climbing"}),
    ("finished with SI prep", {"category": "SI Prep", "job": "si_prep"}),
    ("stop the climbing timer", {"category": "Climbing"}),
    ("stop tutoring at 6", {"category": "Work", "job": "tutoring", "at": ny(17, 18)}),
    ("stop the timer", {}),
    ("stop timer", {}),
])
def test_stop_with_activity(text, expected):
    assert one(text) == ("stop_timer", expected)
