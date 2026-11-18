"""LLM fallback for /log: text the quick-add parser can't read becomes action calls.

The model never writes to the database. It returns tool calls; `journal.py`
applies them through `apply_action` like any other input, so validation, undo
and the action log all work the same. Only `GeminiExtractor` knows about the
provider; swapping models means writing another class with the same `extract`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import JOBS, get_settings
from app.models import Category, Task, TimeEntry
from app.timeutil import LOCAL_TZ, local_day_bounds, local_today

SYSTEM_PROMPT = """\
You turn the user's spoken or typed log into planner actions by calling tools.

Rules:
- Match mentions to open_tasks by meaning before creating a new task; use its id.
- Resolve relative times ("this morning", "from 2 to 4", "friday") against now.
- Give every time as local New York time in ISO 8601 without an offset, e.g. 2026-11-17T14:00:00.
- Never invent a time or duration that was not said. If one is needed and missing, call clarify.
- A vague amount ("about an hour", "a couple hours") is fine: use it and set confirmed=false.
- "Clocking in/out", "off work" and named jobs are work time; set job to one of the listed jobs.
- Use only category names from the list. If none fits, leave category out.
- One statement can produce several actions; return all of them.
- If something is ambiguous (which task, which time), call clarify alone instead of guessing.
- If nothing is actionable (feelings, a diary note), call no tools.

A time entry needs both ends, or a duration. "now" counts only when the user means
the present ("just finished", "until now"). Examples, with now = 17:30:
- "climbed from 2 to 4" -> log_time 14:00-16:00
- "an hour of applications" -> log_time duration_min=60, confirmed=false
- "climbed until 5" -> clarify "When did you start climbing?" (start was not said)
- "tutored this morning" -> clarify "What time did tutoring start and end?"
- "just finished 45 min of SI prep" -> log_time duration_min=45, ending now
"""

_TIME = {"type": "string", "description": "Local New York time, ISO 8601, no offset"}
_CATEGORY = {"type": "string", "description": "A category name from the list"}
_JOB = {"type": "string", "enum": sorted(JOBS), "description": "Only for paid work"}
_TASK_ID = {"type": "integer", "description": "id from open_tasks"}

# Hand-written so the model sees only what it should set (no source, ids of
# categories, links). tests/test_extract.py checks every field exists on the
# action's params model.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_task",
        "description": "Create a new task (only if no open task matches).",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "category": _CATEGORY,
                "due_at": _TIME,
                "scheduled_start": _TIME,
                "scheduled_end": _TIME,
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark an open task done.",
        "parameters": {
            "type": "object",
            "properties": {"task_id": _TASK_ID, "completed_at": _TIME},
            "required": ["task_id"],
        },
    },
    {
        "name": "update_task",
        "description": "Reschedule, rename, recategorize or change the status of an open task.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": _TASK_ID,
                "fields": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "category": _CATEGORY,
                        "status": {"type": "string", "enum": ["todo", "doing", "done", "skipped"]},
                        "due_at": _TIME,
                        "scheduled_start": _TIME,
                        "scheduled_end": _TIME,
                    },
                },
            },
            "required": ["task_id", "fields"],
        },
    },
    {
        "name": "log_time",
        "description": (
            "Record time already spent. Give started_at and ended_at, or duration_min "
            "(with started_at or ended_at if said; otherwise it ends now)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": _CATEGORY,
                "started_at": _TIME,
                "ended_at": _TIME,
                "duration_min": {"type": "integer"},
                "task_id": _TASK_ID,
                "job": _JOB,
                "note": {"type": "string"},
                "confirmed": {
                    "type": "boolean",
                    "description": "false when the duration was vague",
                },
            },
        },
    },
    {
        "name": "start_timer",
        "description": "Start a live timer now (also clocking in). Stops any running timer.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": _CATEGORY,
                "task_id": _TASK_ID,
                "job": _JOB,
                "note": {"type": "string"},
            },
        },
    },
    {
        "name": "stop_timer",
        "description": (
            "Stop the running timer (also clocking out). Pass category or job only to "
            "make sure the right timer is stopped."
        ),
        "parameters": {
            "type": "object",
            "properties": {"at": _TIME, "category": _CATEGORY, "job": _JOB},
        },
    },
    {
        "name": "clarify",
        "description": "Ask one question instead of guessing. Nothing is applied.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question"],
        },
    },
]
_TOOL_PROPS = {t["name"]: t["parameters"]["properties"] for t in TOOLS}


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Clarify:
    question: str
    options: list[str] = field(default_factory=list)


@dataclass
class Extraction:
    calls: list[ToolCall] = field(default_factory=list)
    clarify: Clarify | None = None


class ExtractionError(Exception):
    """The model couldn't be reached or answered unusably. The journal entry stays."""


class Extractor(Protocol):
    def extract(self, system: str, prompt: str, tools: list[dict[str, Any]]) -> Extraction: ...


def _keep(args: dict[str, Any], props: dict[str, Any]) -> dict[str, Any]:
    """Drop fields the tool doesn't declare and nulls (a null in update_task
    would clear a field, which the model never means)."""
    out = {}
    for key, value in args.items():
        if key not in props or value is None:
            continue
        if props[key].get("type") == "object" and isinstance(value, dict):
            value = _keep(value, props[key]["properties"])
        out[key] = value
    return out


def to_extraction(raw_calls: list[tuple[str, dict[str, Any]]]) -> Extraction:
    """Provider-neutral cleanup of raw (name, args) calls. A clarify wins over
    everything else: the answer re-runs extraction on the whole text, so applying
    the other calls now would apply them twice."""
    calls: list[ToolCall] = []
    for name, args in raw_calls:
        props = _TOOL_PROPS.get(name)
        if props is None:
            continue
        args = _keep(args, props)
        if name == "clarify":
            if args.get("question"):
                options = [str(o) for o in args.get("options", [])]
                return Extraction(clarify=Clarify(args["question"], options))
            continue
        calls.append(ToolCall(name, _normalize(name, args)))
    return Extraction(calls=calls)


def _normalize(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Repair predictable model slips the actions would otherwise reject or misfile."""
    if name in ("log_time", "start_timer") and args.get("job") in JOBS and "category" not in args:
        args["category"] = JOBS[args["job"]]  # same default clock-in uses
    if name == "log_time" and "started_at" in args and "ended_at" in args:
        args.pop("duration_min", None)  # redundant; the action refuses both
    return args


def _local(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%a %Y-%m-%d %H:%M")


def build_prompt(
    session: Session, now: datetime, text: str, followup: tuple[str, str] | None = None
) -> str:
    """Context the model needs to resolve the text: time, categories, open tasks,
    the running timer and today's entries. `now` is when the text was recorded."""
    cats = {c.id: c for c in session.scalars(select(Category).order_by(Category.name))}
    lines = [f"now: {_local(now)} (America/New_York)"]
    lines.append(
        "categories: "
        + ", ".join(f"{c.name}{' (work)' if c.is_work else ''}" for c in cats.values())
    )
    lines.append("jobs: " + ", ".join(sorted(JOBS)))

    tasks = session.scalars(
        select(Task).where(Task.status.in_(("todo", "doing")))
        .order_by(Task.due_at.asc().nulls_last(), Task.id).limit(100)
    )
    lines.append("open_tasks:")
    for t in tasks:
        due = f", due {_local(t.due_at)}" if t.due_at else ""
        lines.append(f"- id {t.id}: {t.title} [{cats[t.category_id].name}{due}]")

    running = session.scalar(select(TimeEntry).where(TimeEntry.ended_at.is_(None)))
    if running:
        job = f" ({running.job})" if running.job else ""
        since = _local(running.started_at)
        lines.append(f"running_timer: {cats[running.category_id].name}{job} since {since}")
    else:
        lines.append("running_timer: none")

    start, end = local_day_bounds(local_today(now))
    entries = session.scalars(
        select(TimeEntry).where(TimeEntry.started_at >= start, TimeEntry.started_at < end,
                                TimeEntry.ended_at.is_not(None))
        .order_by(TimeEntry.started_at)
    )
    lines.append("today_entries:")
    for e in entries:
        job = f" ({e.job})" if e.job else ""
        lines.append(f"- {cats[e.category_id].name}{job} {_local(e.started_at)}-"
                     f"{e.ended_at.astimezone(LOCAL_TZ):%H:%M}")

    lines += ["", "log:", text]
    if followup:
        question, answer = followup
        lines += ["", f"You asked: {question}", f"Answer: {answer}"]
    return "\n".join(lines)


class GeminiExtractor:
    def __init__(self, api_key: str, model: str):
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=30_000)
        )
        self._model = model

    def extract(self, system: str, prompt: str, tools: list[dict[str, Any]]) -> Extraction:
        types = self._types
        decls = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"],
                parameters_json_schema=t["parameters"],
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
        )
        try:
            resp = self._client.models.generate_content(
                model=self._model, contents=prompt, config=config
            )
        except Exception as e:  # network, quota, bad key: all mean "not this time"
            raise ExtractionError(str(e) or type(e).__name__) from e
        return to_extraction([(fc.name, dict(fc.args or {})) for fc in resp.function_calls or []])


@lru_cache
def _gemini(api_key: str, model: str) -> GeminiExtractor:
    return GeminiExtractor(api_key, model)


def get_extractor() -> Extractor | None:
    """FastAPI dependency; None when no key is configured (fallback off)."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    return _gemini(settings.gemini_api_key, settings.gemini_model)
