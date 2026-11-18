"""Deterministic quick-add parser for the /log box.

Pure: text + reference time + category names in, intents out. No DB access.
Returns None when the line isn't understood; /log then keeps the journal entry
and (from Phase 2) hands the text to Claude.

Grammar (case-insensitive):
  task <title> [#category] [due: today|tonight|tomorrow|mon..sun|m/d] [5pm]
  done <task title words>                 -> complete the one open task matching
  start <activity> [at 2pm]               -> start_timer
  stop | done | end [at 5pm]              -> stop_timer
  stop|done|finished [with] <activity> [timer] [at 5pm] -> stop_timer, only if that's what's running
  clock in [for] <job> [at 3pm] / clock out [at 6pm]
  <activity> <duration|range> [yesterday] [note...]
      durations: 2h, 1.5h, 2h30m, 45m, 90 min; prefix ~/about/around = estimate
      ranges:    3-6pm, 3pm-6pm, 2:30-4, 14:00-16:00, from 2 to 4
  climbing logs become log_climb; the note is "[at] <gym>[, notes]":
      climb 2h vital / climbed 2-4 at Vital, worked the overhang / climb 1h, felt strong
      (a note starting with "with", "felt", ... is all notes, no gym)
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from app.config import ACTIVITIES, CLIMBING_CATEGORY
from app.timeutil import LOCAL_TZ


@dataclass
class Intent:
    kind: str  # an action type, or "complete_task_by_title"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Activity:
    category: str
    job: str | None


# ---------------------------------------------------------------- times

_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?"
_RANGE = re.compile(
    rf"(?:\bfrom\s+)?\b{_TIME}\s*(?:-|–|\bto\b|\buntil\b|\btill\b)\s*{_TIME}(?![\w:])"
)
_AT = re.compile(rf"\s+(?:at|@)\s+{_TIME}$")
_UNIT_END = r"(?![a-z])"
_DURATION = re.compile(
    rf"\b(?:(?P<h>\d+(?:\.\d+)?)\s*(?:hours?|hrs|hr|h){_UNIT_END}"
    rf"\s*(?:(?P<hm>\d+)\s*(?:minutes?|mins|min|m){_UNIT_END})?"
    rf"|(?P<m>\d+)\s*(?:minutes?|mins|min|m){_UNIT_END})"
)
_ESTIMATE = re.compile(r"(?:^|\s)(?:~|(?:about|around|roughly|approximately|approx\.?)(?![a-z]))")
_YESTERDAY = re.compile(r"\byesterday\b")


def _meridiem(ap: str | None) -> str | None:
    return None if not ap else ("pm" if ap.startswith("p") else "am")


def _to24(hour: int, ap: str | None) -> int:
    if ap == "am":
        return 0 if hour == 12 else hour
    if ap == "pm":
        return hour if hour == 12 else hour + 12
    return hour


def _guess_ap(hour: int) -> str:
    """No am/pm given: 8-11 read as morning, 12 and 1-7 as afternoon/evening."""
    return "am" if 8 <= hour <= 11 else "pm"


def _clock(h: str, m: str | None, ap: str | None, guess: bool = True) -> tuple[int, int, bool]:
    """-> (hour24, minute, had_explicit_meridiem_or_24h)."""
    hour, minute, mer = int(h), int(m or 0), _meridiem(ap)
    if hour > 23 or minute > 59:
        raise ValueError("bad time")
    if hour > 12 or hour == 0:
        return hour, minute, True
    if mer:
        return _to24(hour, mer), minute, True
    return (_to24(hour, _guess_ap(hour)) if guess else hour), minute, False


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=LOCAL_TZ)


def _range(match: re.Match, day: date) -> tuple[datetime, datetime]:
    h1, m1, a1, h2, m2, a2 = match.groups()
    mer1, mer2 = _meridiem(a1), _meridiem(a2)
    s_h, s_m, s_exp = _clock(h1, m1, a1)
    e_h, e_m, e_exp = _clock(h2, m2, a2)
    if e_exp and not s_exp and mer2:
        # "3-6pm": start borrows the end's meridiem; "11-1pm": flip to keep start < end.
        s_h = _to24(int(h1), mer2)
        if (s_h, s_m) >= (e_h, e_m):
            s_h = _to24(int(h1), "am" if mer2 == "pm" else "pm")
    elif s_exp and not e_exp and mer1:
        e_h = _to24(int(h2), mer1)
        if (e_h, e_m) <= (s_h, s_m):
            e_h = _to24(int(h2), "pm" if mer1 == "am" else "am")
    start, end = _at(day, s_h, s_m), _at(day, e_h, e_m)
    if end <= start:
        end += timedelta(days=1)  # overnight
    return start, end


def _duration(match: re.Match) -> int:
    if match["h"]:
        return round(float(match["h"]) * 60) + int(match["hm"] or 0)
    return int(match["m"])


def _strip_at(text: str, day: date) -> tuple[str, datetime | None]:
    m = _AT.search(text)
    if not m:
        return text, None
    hour, minute, _ = _clock(*m.groups())
    return text[: m.start()].strip(), _at(day, hour, minute)


# ---------------------------------------------------------------- due dates

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_WORD = (
    r"today|tonight|tomorrow|tmrw?|tmr"
    r"|mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?"
    r"|sat(?:urday)?|sun(?:day)?|\d{1,2}/\d{1,2}"
)
_DUE = re.compile(
    rf"\s+(?:(?:due|by|on)\s+)?(?:(?P<day>{_DAY_WORD})\b)?"
    rf"(?:\s*(?:at\s+)?(?P<h>\d{{1,2}})(?::(?P<m>\d{{2}}))?\s*(?P<ap>am|pm))?$"
)


def _due_day(word: str, today: date) -> date:
    if word in ("today", "tonight"):
        return today
    if word.startswith("tm") or word == "tomorrow":
        return today + timedelta(days=1)
    if "/" in word:
        month, dom = map(int, word.split("/"))
        d = date(today.year, month, dom)
        return d if d >= today else date(today.year + 1, month, dom)
    target = _WEEKDAYS.index(word[:3])
    return today + timedelta(days=(target - today.weekday()) % 7)  # today counts


def _parse_due(text: str, today: date) -> tuple[str, datetime | None]:
    m = _DUE.search(text)
    if not m or not (m["day"] or m["h"]):
        return text, None
    title = text[: m.start()].strip()
    if not title:
        return text, None
    day = _due_day(m["day"], today) if m["day"] else today
    if m["h"]:
        hour, minute, _ = _clock(m["h"], m["m"], m["ap"])
    elif m["day"] == "tonight":
        hour, minute = 21, 0
    else:
        hour, minute = 23, 59
    return title, _at(day, hour, minute)


# ---------------------------------------------------------------- activities


def _vocabulary(category_names: list[str]) -> list[tuple[str, Activity]]:
    vocab = {w: Activity(c, j) for w, (c, j) in ACTIVITIES.items()}
    for name in category_names:
        vocab.setdefault(name.lower(), Activity(name, None))
    return sorted(vocab.items(), key=lambda kv: -len(kv[0]))  # longest match wins


def _match_activity(
    text: str, vocab: list[tuple[str, Activity]]
) -> tuple[Activity | None, str]:
    for word, act in vocab:
        if text == word or text.startswith(word + " "):
            return act, text[len(word):].strip()
    return None, text


_HASHTAG = re.compile(r"(?:^|\s)#([\w-]+)")


def _hashtag_category(text: str, vocab) -> tuple[str, str | None]:
    m = _HASHTAG.search(text)
    if not m:
        return text, None
    tag = m[1].replace("-", " ").replace("_", " ").lower()
    act = dict(vocab).get(tag)
    category = act.category if act else tag  # unknown tags are rejected by the action
    return (text[: m.start()] + text[m.end():]).strip(), category


# ---------------------------------------------------------------- entry point

_TASK = re.compile(r"^(?:task|todo|add)\s+(?P<rest>.+)$")
_DONE_TASK = re.compile(r"^(?:done|finished|did|completed?)\s+(?P<rest>.+)$")
_STOP_WORD = r"(?:stop|stopped|stopping|done|end|ended|finish|finished)"
_STOP = re.compile(rf"^{_STOP_WORD}(?:\s+(?:the\s+)?timer)?$")
_STOP_ACTIVITY = re.compile(
    rf"^{_STOP_WORD}(?:\s+with)?(?:\s+the)?\s+(?P<rest>.+?)(?:\s+timer)?$"
)
_START = re.compile(r"^(?:start|starting|started|begin)\s+(?:the\s+)?(?P<rest>.+)$")
_CLOCK_IN = re.compile(r"^(?:clock(?:ing|ed)?\s+in|clock-in)(?:\s+(?:for|to|at))?\s*(?P<rest>.*)$")
_CLOCK_OUT = re.compile(r"^(?:clock(?:ing|ed)?\s+out|clock-out|off work|done with work)$")


def parse(raw: str, now: datetime, category_names: list[str]) -> list[Intent] | None:
    text = " ".join(raw.strip().lower().split()).rstrip(".!")
    original = " ".join(raw.strip().split()).rstrip(".!")
    if not text:
        return None
    local_now = now.astimezone(LOCAL_TZ)
    today = local_now.date()
    vocab = _vocabulary(category_names)
    try:
        return _parse(text, original, local_now, today, vocab)
    except ValueError:
        return None


def _parse(text, original, local_now, today, vocab) -> list[Intent] | None:
    # task <title> ... (title keeps the original casing)
    if m := _TASK.match(text):
        rest = original[m.start("rest"):]
        rest, category = _hashtag_category(rest, vocab)
        title, due = _parse_due(rest, today)
        payload: dict[str, Any] = {"title": title}
        if category:
            payload["category"] = category
        if due:
            payload["due_at"] = due
        return [Intent("create_task", payload)]

    # timers / shifts
    body, at = _strip_at(text, today)
    if _CLOCK_OUT.match(body):
        return [Intent("stop_timer", _with_at({"require_work": True}, at))]
    if m := _CLOCK_IN.match(body):
        act, leftover = _match_activity(m["rest"], vocab)
        if act is None or act.job is None or leftover:
            return None
        return [Intent("start_timer", _with_at(_activity_payload(act), at))]
    if _STOP.match(body):
        return [Intent("stop_timer", _with_at({}, at))]
    if m := _STOP_ACTIVITY.match(body):
        # "stop climbing": only a bare activity counts; "done SI slides" (a task) and
        # "done climbing 2h" (a time log) fall through to the rules below.
        act, leftover = _match_activity(m["rest"], vocab)
        if act is not None and not leftover:
            return [Intent("stop_timer", _with_at(_activity_payload(act), at))]
    if m := _START.match(body):
        act, leftover = _match_activity(m["rest"], vocab)
        if act is None:
            return None
        payload = _activity_payload(act)
        if leftover:
            payload["note"] = leftover
        return [Intent("start_timer", _with_at(payload, at))]

    # done <task> -- unless it's a time log like "done climbing 2h"
    if m := _DONE_TASK.match(text):
        rest_original = original[m.start("rest"):]
        logged = _parse_log(m["rest"], rest_original, local_now, today, vocab)
        return logged or [Intent("complete_task_by_title", {"query": rest_original})]

    return _parse_log(text, original, local_now, today, vocab)


def _parse_log(text, original, local_now, today, vocab) -> list[Intent] | None:
    act, rest = _match_activity(text, vocab)
    if act is None:
        return None
    original_rest = original[len(original) - len(rest):] if rest else ""

    day = today
    if _YESTERDAY.search(rest):
        day = today - timedelta(days=1)
        rest = _YESTERDAY.sub(" ", rest)
        original_rest = re.sub(r"(?i)\byesterday\b", " ", original_rest)

    estimate = bool(_ESTIMATE.search(" " + rest))
    payload = _activity_payload(act)
    if r := _RANGE.search(rest):
        payload["started_at"], payload["ended_at"] = _range(r, day)
        span = (r.start(), r.end())
    elif d := _DURATION.search(rest):
        payload["duration_min"] = _duration(d)
        if day != today:
            # "climbed 2h yesterday": no clock time was said, so it's an estimate placed
            # at the end of yesterday's evening; review can fix it.
            payload["ended_at"] = _at(day, 21, 0)
            estimate = True
        else:
            payload["ended_at"] = local_now
        span = (d.start(), d.end())
    else:
        return None

    note = (original_rest[: span[0]] + " " + original_rest[span[1]:])
    note = _ESTIMATE.sub(" ", " " + note)
    note = " ".join(note.split()).strip(" ,-")
    if note:
        payload["note"] = note
    if estimate:
        payload["confirmed"] = False
    if act.category == CLIMBING_CATEGORY:
        return [Intent("log_climb", _climb_payload(payload))]
    return [Intent("log_time", payload)]


_NOTE_SPLIT = re.compile(r"\s*[,;:]\s*|\s+[-–—]\s+")
_NOT_A_GYM = re.compile(r"(?i)^(?:with|felt|feeling|and|worked|working|did|on|for|projecting)\b")


def _climb_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """log_time payload -> log_climb: the note's first part is the gym."""
    climb = {k: v for k, v in payload.items() if k not in ("category", "note")}
    note = payload.get("note", "")
    if not note:
        return climb
    if _NOT_A_GYM.match(note):
        climb["notes"] = note
        return climb
    gym, rest = (_NOTE_SPLIT.split(note, maxsplit=1) + [""])[:2]
    gym = re.sub(r"(?i)^(?:at|@)\s+", "", gym).strip()
    if gym:
        climb["gym"] = gym
    if rest:
        climb["notes"] = rest
    return climb


def _activity_payload(act: Activity) -> dict[str, Any]:
    payload: dict[str, Any] = {"category": act.category}
    if act.job:
        payload["job"] = act.job
    return payload


def _with_at(payload: dict[str, Any], at: datetime | None) -> dict[str, Any]:
    if at is not None:
        payload["at"] = at
    return payload
