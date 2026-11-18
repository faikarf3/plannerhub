from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import check_job, get_or_404, resolve_category, set_fields
from app.config import MIN_ENTRY_MINUTES
from app.models import Category, Task, TimeEntry
from app.schemas import TimeEntryOut
from app.timeutil import AwareDatetime, fmt_duration, fmt_local, minutes_between

TimeSource = Literal["timer", "voice", "manual", "calendar", "pipeline"]


class LogTime(BaseModel):
    """A past entry: give started_at+ended_at, or duration_min (+ either end; default ends now)."""

    category: str | None = None
    category_id: int | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    duration_min: int | None = Field(default=None, gt=0)
    task_id: int | None = None
    job: str | None = None
    note: str | None = None
    confirmed: bool = True
    source: TimeSource = "manual"


class TimeEntryPatch(BaseModel):
    category: str | None = None
    category_id: int | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    task_id: int | None = None
    job: str | None = None
    note: str | None = None
    confirmed: bool | None = None


class UpdateTimeEntry(BaseModel):
    entry_id: int
    fields: TimeEntryPatch


class StartTimer(BaseModel):
    category: str | None = None
    category_id: int | None = None
    task_id: int | None = None
    job: str | None = None
    note: str | None = None
    at: AwareDatetime | None = None  # offline queue: when the tap/recording happened
    source: TimeSource = "timer"


class StopTimer(BaseModel):
    at: AwareDatetime | None = None
    require_work: bool = False  # clock-out only stops a work timer
    # "stop climbing": refuse rather than stop a different timer.
    category: str | None = None
    job: str | None = None


class EntryRef(BaseModel):
    entry_id: int


class TimeEntryFieldValues(BaseModel):
    category_id: int | None = None
    task_id: int | None = None
    job: str | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    duration_min: int | None = None
    confirmed: bool | None = None
    note: str | None = None


class RestoreTimeEntryFields(BaseModel):
    entry_id: int
    values: TimeEntryFieldValues


class RestoreTimeEntry(BaseModel):
    entry: TimeEntryOut


def _result(entry: TimeEntry) -> dict:
    return {"time_entry": TimeEntryOut.model_validate(entry).model_dump(mode="json")}


def _snapshot(entry: TimeEntry) -> dict:
    return TimeEntryOut.model_validate(entry).model_dump(mode="json")


def _restore_fields_step(entry_id: int, before: dict) -> Step:
    return Step("restore_time_entry_fields", {"entry_id": entry_id, "values": before})


def _check_task(ctx: ActionContext, task_id: int | None) -> None:
    if task_id is not None:
        get_or_404(ctx.session, Task, task_id)


def running_timer(ctx: ActionContext, *, lock: bool = False) -> TimeEntry | None:
    q = select(TimeEntry).where(TimeEntry.ended_at.is_(None))
    return ctx.session.scalar(q.with_for_update() if lock else q)


def _close(ctx: ActionContext, entry: TimeEntry, at) -> tuple[str, list[Step]]:
    """Stop a running entry at `at`. Returns (summary, inverse). Entries under the
    minimum are dropped as accidental taps."""
    if at < entry.started_at:
        raise ActionError(f"stop time {fmt_local(at)} is before the timer started")
    category = ctx.session.get(Category, entry.category_id)
    label = entry.job or category.name
    minutes = minutes_between(entry.started_at, at)
    if minutes < MIN_ENTRY_MINUTES:
        snapshot = _snapshot(entry)
        ctx.session.delete(entry)
        ctx.session.flush()
        return (
            f"Dropped {label} timer (under {MIN_ENTRY_MINUTES} min)",
            [Step("restore_time_entry", {"entry": snapshot})],
        )
    before = set_fields(entry, {"ended_at": at, "duration_min": minutes}, TimeEntryOut)
    ctx.session.flush()
    return (
        f"Stopped {label} at {fmt_local(at)} ({fmt_duration(minutes)})",
        [_restore_fields_step(entry.id, before)],
    )


@action("log_time", LogTime)
def log_time(ctx: ActionContext, p: LogTime) -> Outcome:
    category = resolve_category(ctx.session, p.category, p.category_id)
    check_job(category, p.job)
    _check_task(ctx, p.task_id)

    start, end = p.started_at, p.ended_at
    if start and end:
        if p.duration_min is not None:
            raise ActionError("give started_at+ended_at or a duration, not both")
    elif p.duration_min is not None:
        span = timedelta(minutes=p.duration_min)
        if start:
            end = start + span
        else:
            end = end or ctx.now
            start = end - span
    else:
        raise ActionError("log_time needs started_at and ended_at, or duration_min "
                          "(use start_timer for a running timer)")
    if end <= start:
        raise ActionError("ended_at must be after started_at")
    minutes = minutes_between(start, end)
    if minutes < MIN_ENTRY_MINUTES:
        raise ActionError(f"entries under {MIN_ENTRY_MINUTES} minutes are not kept")

    entry = TimeEntry(
        category_id=category.id, task_id=p.task_id, job=p.job, started_at=start, ended_at=end,
        duration_min=minutes, source=p.source, confirmed=p.confirmed, note=p.note,
    )
    ctx.session.add(entry)
    ctx.session.flush()
    label = p.job or category.name
    summary = f"Logged {fmt_duration(minutes)} {label}, {fmt_local(start)}–{fmt_local(end)}"
    if not p.confirmed:
        summary += " (estimate)"
    return Outcome(summary, [Step("delete_time_entry", {"entry_id": entry.id})], _result(entry))


@action("update_time_entry", UpdateTimeEntry)
def update_time_entry(ctx: ActionContext, p: UpdateTimeEntry) -> Outcome:
    entry = get_or_404(ctx.session, TimeEntry, p.entry_id, lock=True)
    patch = p.fields.model_dump(exclude_unset=True)
    if not patch:
        raise ActionError("update_time_entry needs at least one field")

    category = ctx.session.get(Category, entry.category_id)
    if "category" in patch or "category_id" in patch:
        category = resolve_category(ctx.session, patch.pop("category", None),
                                    patch.pop("category_id", None))
        patch["category_id"] = category.id
    check_job(category, patch.get("job", entry.job))
    if "task_id" in patch:
        _check_task(ctx, patch["task_id"])
    if patch.get("started_at", 0) is None:
        raise ActionError("started_at cannot be cleared")
    if "ended_at" in patch and patch["ended_at"] is None and entry.ended_at is not None:
        raise ActionError("cannot reopen a finished entry; start a new timer instead")

    start = patch.get("started_at", entry.started_at)
    end = patch.get("ended_at", entry.ended_at)
    if end is not None:
        if end <= start:
            raise ActionError("ended_at must be after started_at")
        minutes = minutes_between(start, end)
        if minutes < MIN_ENTRY_MINUTES:
            raise ActionError(f"entries under {MIN_ENTRY_MINUTES} minutes are not kept")
        patch["duration_min"] = minutes

    before = set_fields(entry, patch, TimeEntryOut)
    ctx.session.flush()
    changed = ", ".join(k for k in patch if k != "duration_min")
    return Outcome(
        f"Updated {entry.job or category.name} entry: {changed}",
        [_restore_fields_step(entry.id, before)],
        _result(entry),
    )


@action("delete_time_entry", EntryRef)
def delete_time_entry(ctx: ActionContext, p: EntryRef) -> Outcome:
    entry = get_or_404(ctx.session, TimeEntry, p.entry_id, lock=True)
    snapshot = _snapshot(entry)
    ctx.session.delete(entry)
    ctx.session.flush()
    return Outcome("Deleted time entry", [Step("restore_time_entry", {"entry": snapshot})])


@action("restore_time_entry", RestoreTimeEntry, internal=True)
def restore_time_entry(ctx: ActionContext, p: RestoreTimeEntry) -> Outcome:
    if ctx.session.get(TimeEntry, p.entry.id) is not None:
        raise ActionError(f"time entry {p.entry.id} already exists", 409)
    if p.entry.ended_at is None and running_timer(ctx) is not None:
        raise ActionError("another timer is running; stop it first", 409)
    values = p.entry.model_dump()
    if values["task_id"] is not None and ctx.session.get(Task, values["task_id"]) is None:
        values["task_id"] = None
    entry = TimeEntry(**values)
    ctx.session.add(entry)
    ctx.session.flush()
    return Outcome("Restored time entry", [Step("delete_time_entry", {"entry_id": entry.id})])


@action("restore_time_entry_fields", RestoreTimeEntryFields, internal=True)
def restore_time_entry_fields(ctx: ActionContext, p: RestoreTimeEntryFields) -> Outcome:
    entry = get_or_404(ctx.session, TimeEntry, p.entry_id, lock=True)
    values = p.values.model_dump(exclude_unset=True)
    if values.get("ended_at", 0) is None and entry.ended_at is not None:
        # Re-opening a timer (undoing a stop) — only if nothing else is running.
        other = running_timer(ctx)
        if other is not None and other.id != entry.id:
            raise ActionError("another timer is running; stop it first", 409)
    before = set_fields(entry, values, TimeEntryOut)
    ctx.session.flush()
    return Outcome("Restored time entry", [_restore_fields_step(entry.id, before)])


@action("start_timer", StartTimer)
def start_timer(ctx: ActionContext, p: StartTimer) -> Outcome:
    category = resolve_category(ctx.session, p.category, p.category_id)
    check_job(category, p.job)
    _check_task(ctx, p.task_id)
    at = p.at or ctx.now

    inverse_tail: list[Step] = []
    stopped = ""
    current = running_timer(ctx, lock=True)
    if current is not None:
        stopped, inverse_tail = _close(ctx, current, at)

    entry = TimeEntry(
        category_id=category.id, task_id=p.task_id, job=p.job, started_at=at,
        source=p.source, note=p.note,
    )
    ctx.session.add(entry)
    ctx.session.flush()

    summary = f"Started {p.job or category.name} at {fmt_local(at)}"
    if stopped:
        summary += f"; {stopped[0].lower()}{stopped[1:]}"
    # Undo: remove the new timer first, then re-open the one it replaced.
    inverse = [Step("delete_time_entry", {"entry_id": entry.id}), *inverse_tail]
    return Outcome(summary, inverse, _result(entry))


@action("stop_timer", StopTimer)
def stop_timer(ctx: ActionContext, p: StopTimer) -> Outcome:
    current = running_timer(ctx, lock=True)
    if current is None:
        raise ActionError("no timer is running", 409)
    if p.require_work and not ctx.session.get(Category, current.category_id).is_work:
        raise ActionError("not clocked in (the running timer is not work)", 409)
    if p.category is not None or p.job is not None:
        running_cat = ctx.session.get(Category, current.category_id)
        expected = resolve_category(ctx.session, p.category, None) if p.category else running_cat
        if expected.id != running_cat.id or (p.job and p.job != current.job):
            running = current.job or running_cat.name
            wanted = p.job or expected.name
            raise ActionError(f"the running timer is {running}, not {wanted}", 409)
    entry_id = current.id
    summary, inverse = _close(ctx, current, p.at or ctx.now)
    entry = ctx.session.get(TimeEntry, entry_id)
    return Outcome(summary, inverse, _result(entry) if entry else {"time_entry": None})
