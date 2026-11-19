"""Repeating weekly schedules and one-week changes to them (skip, move, confirm)."""

from datetime import date, time
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import check_job, get_or_404, resolve_category, set_fields
from app.actions.time_entries import LogTime, log_time
from app.config import JOBS
from app.models import Category, Schedule, ScheduleException, TimeEntry
from app.schedule import describe, label, occurs_on, planned_times
from app.schemas import ScheduleExceptionOut, ScheduleOut
from app.timeutil import AwareDatetime, fmt_local, local_today

Weekdays = list[int]


def _clean_days(days: Weekdays | None) -> Weekdays | None:
    if days is None:
        return None
    if any(d < 0 or d > 6 for d in days):
        raise ValueError("weekdays are 0 (Monday) to 6 (Sunday)")
    return sorted(set(days))


class CreateSchedule(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    category: str | None = None  # defaults to the job's category (config.JOBS)
    category_id: int | None = None
    job: str | None = None
    weekdays: Weekdays = Field(min_length=1)  # 0 = Monday
    start_time: time
    end_time: time  # earlier than start_time = ends the next day
    starts_on: date | None = None  # default today
    until: date | None = None  # last day it can start on; None = no end
    note: str | None = None

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: Weekdays | None) -> Weekdays | None:
        return _clean_days(v)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.start_time == self.end_time:
            raise ValueError("start_time and end_time can't be the same")
        return self


class SchedulePatch(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    category: str | None = None
    category_id: int | None = None
    job: str | None = None
    weekdays: Weekdays | None = None
    start_time: time | None = None
    end_time: time | None = None
    starts_on: date | None = None
    until: date | None = None
    note: str | None = None

    @field_validator("weekdays")
    @classmethod
    def _days(cls, v: Weekdays | None) -> Weekdays | None:
        return _clean_days(v)


class UpdateSchedule(BaseModel):
    schedule_id: int
    fields: SchedulePatch


class ScheduleRef(BaseModel):
    schedule_id: int


class ScheduleFieldValues(BaseModel):
    title: str | None = None
    category_id: int | None = None
    job: str | None = None
    weekdays: Weekdays | None = None
    start_time: time | None = None
    end_time: time | None = None
    starts_on: date | None = None
    until: date | None = None
    note: str | None = None


class RestoreScheduleFields(BaseModel):
    schedule_id: int
    values: ScheduleFieldValues


class RestoreSchedule(BaseModel):
    schedule: ScheduleOut
    exceptions: list[ScheduleExceptionOut] = []


class OccurrenceRef(BaseModel):
    schedule_id: int
    on_date: date  # the local date the occurrence starts on


class MoveOccurrence(OccurrenceRef):
    started_at: AwareDatetime
    ended_at: AwareDatetime


class ConfirmOccurrence(OccurrenceRef):
    """Log a planned occurrence as done; times default to the plan."""

    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    note: str | None = None


class ExceptionState(BaseModel):
    skipped: bool = False
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    time_entry_id: int | None = None


class RestoreOccurrence(OccurrenceRef):
    state: ExceptionState | None  # None = no exception row


# ---------------------------------------------------------------- helpers


def _result(s: Schedule) -> dict:
    return {"schedule": ScheduleOut.model_validate(s).model_dump(mode="json")}


def _check_rule(s: Schedule) -> None:
    if s.start_time == s.end_time:
        raise ActionError("start_time and end_time can't be the same")
    if not s.weekdays:
        raise ActionError("a schedule needs at least one weekday")
    if s.until is not None and s.until < s.starts_on:
        raise ActionError("until can't be before starts_on")


def _name(ctx: ActionContext, s: Schedule) -> str:
    return label(s, ctx.session.get(Category, s.category_id))


def _day(d: date) -> str:
    return d.strftime("%a %b %-d")


# ---------------------------------------------------------------- rules


@action("create_schedule", CreateSchedule)
def create_schedule(ctx: ActionContext, p: CreateSchedule) -> Outcome:
    name = p.category or (JOBS.get(p.job) if p.job else None)
    category = resolve_category(ctx.session, name, p.category_id)
    check_job(category, p.job)
    s = Schedule(
        title=p.title, category_id=category.id, job=p.job, weekdays=p.weekdays,
        start_time=p.start_time, end_time=p.end_time,
        starts_on=p.starts_on or local_today(ctx.now), until=p.until, note=p.note,
    )
    _check_rule(s)
    ctx.session.add(s)
    ctx.session.flush()
    return Outcome(f"Added repeat: {label(s, category)}, {describe(s)}",
                   [Step("delete_schedule", {"schedule_id": s.id})], _result(s))


@action("update_schedule", UpdateSchedule)
def update_schedule(ctx: ActionContext, p: UpdateSchedule) -> Outcome:
    s = get_or_404(ctx.session, Schedule, p.schedule_id, lock=True)
    patch = p.fields.model_dump(exclude_unset=True)
    if not patch:
        raise ActionError("update_schedule needs at least one field")
    for required in ("weekdays", "start_time", "end_time", "starts_on"):
        if required in patch and patch[required] is None:
            raise ActionError(f"{required} can't be cleared")
    category = ctx.session.get(Category, s.category_id)
    if "category" in patch or "category_id" in patch:
        category = resolve_category(ctx.session, patch.pop("category", None),
                                    patch.pop("category_id", None))
        patch["category_id"] = category.id
    check_job(category, patch.get("job", s.job))

    before = set_fields(s, patch, ScheduleOut)
    _check_rule(s)
    ctx.session.flush()
    return Outcome(f"Updated repeat: {label(s, category)}, {describe(s)}",
                   [Step("restore_schedule_fields", {"schedule_id": s.id, "values": before})],
                   _result(s))


@action("delete_schedule", ScheduleRef)
def delete_schedule(ctx: ActionContext, p: ScheduleRef) -> Outcome:
    s = get_or_404(ctx.session, Schedule, p.schedule_id, lock=True)
    name = _name(ctx, s)
    snapshot = {
        "schedule": ScheduleOut.model_validate(s).model_dump(mode="json"),
        "exceptions": [
            ScheduleExceptionOut.model_validate(e).model_dump(mode="json")
            for e in ctx.session.scalars(
                select(ScheduleException).where(ScheduleException.schedule_id == s.id))
        ],
    }
    ctx.session.delete(s)  # exceptions cascade; logged time entries stay
    ctx.session.flush()
    return Outcome(f"Deleted repeat: {name}", [Step("restore_schedule", snapshot)])


@action("restore_schedule", RestoreSchedule, internal=True)
def restore_schedule(ctx: ActionContext, p: RestoreSchedule) -> Outcome:
    if ctx.session.get(Schedule, p.schedule.id) is not None:
        raise ActionError(f"schedule {p.schedule.id} already exists", 409)
    s = Schedule(**p.schedule.model_dump())
    ctx.session.add(s)
    ctx.session.flush()
    for e in p.exceptions:
        values = e.model_dump()
        if values["time_entry_id"] and ctx.session.get(TimeEntry, values["time_entry_id"]) is None:
            values["time_entry_id"] = None
        ctx.session.add(ScheduleException(**values))
    ctx.session.flush()
    return Outcome(f"Restored repeat: {_name(ctx, s)}",
                   [Step("delete_schedule", {"schedule_id": s.id})])


@action("restore_schedule_fields", RestoreScheduleFields, internal=True)
def restore_schedule_fields(ctx: ActionContext, p: RestoreScheduleFields) -> Outcome:
    s = get_or_404(ctx.session, Schedule, p.schedule_id, lock=True)
    before = set_fields(s, p.values.model_dump(exclude_unset=True), ScheduleOut)
    return Outcome(f"Restored repeat: {_name(ctx, s)}",
                   [Step("restore_schedule_fields", {"schedule_id": s.id, "values": before})])


# ---------------------------------------------------------------- one occurrence


def _occurrence(ctx: ActionContext, p: OccurrenceRef) -> tuple[Schedule, ScheduleException | None]:
    s = get_or_404(ctx.session, Schedule, p.schedule_id, lock=True)
    if not occurs_on(s, p.on_date):
        raise ActionError(f"{_name(ctx, s)} doesn't happen on {_day(p.on_date)}")
    exc = ctx.session.scalar(select(ScheduleException).where(
        ScheduleException.schedule_id == s.id, ScheduleException.on_date == p.on_date
    ).with_for_update())
    return s, exc


def _set_exception(ctx: ActionContext, s: Schedule, exc: ScheduleException | None,
                   on_date: date, values: dict) -> Step:
    """Apply `values` to the occurrence's exception row (creating it), and return
    the step that puts it back as it was."""
    before = None if exc is None else ExceptionState.model_validate(
        {k: getattr(exc, k) for k in ExceptionState.model_fields}).model_dump(mode="json")
    if exc is None:
        exc = ScheduleException(schedule_id=s.id, on_date=on_date)
        ctx.session.add(exc)
    for key, value in values.items():
        setattr(exc, key, value)
    ctx.session.flush()
    return Step("restore_occurrence",
                {"schedule_id": s.id, "on_date": on_date.isoformat(), "state": before})


def _not_done(ctx: ActionContext, s: Schedule, exc: ScheduleException | None, on: date) -> None:
    if exc is not None and exc.time_entry_id is not None:
        raise ActionError(f"{_name(ctx, s)} on {_day(on)} is already logged; "
                          "change or delete its time entry instead", 409)


@action("skip_occurrence", OccurrenceRef)
def skip_occurrence(ctx: ActionContext, p: OccurrenceRef) -> Outcome:
    s, exc = _occurrence(ctx, p)
    _not_done(ctx, s, exc, p.on_date)
    if exc is not None and exc.skipped:
        raise ActionError(f"{_name(ctx, s)} on {_day(p.on_date)} is already skipped", 409)
    step = _set_exception(ctx, s, exc, p.on_date, {"skipped": True})
    return Outcome(f"Skipped {_name(ctx, s)} on {_day(p.on_date)}", [step])


@action("move_occurrence", MoveOccurrence)
def move_occurrence(ctx: ActionContext, p: MoveOccurrence) -> Outcome:
    if p.ended_at <= p.started_at:
        raise ActionError("ended_at must be after started_at")
    s, exc = _occurrence(ctx, p)
    _not_done(ctx, s, exc, p.on_date)
    step = _set_exception(ctx, s, exc, p.on_date,
                          {"skipped": False, "started_at": p.started_at, "ended_at": p.ended_at})
    return Outcome(f"Moved {_name(ctx, s)} on {_day(p.on_date)} to "
                   f"{fmt_local(p.started_at)}–{fmt_local(p.ended_at)}", [step])


@action("confirm_occurrence", ConfirmOccurrence)
def confirm_occurrence(ctx: ActionContext, p: ConfirmOccurrence) -> Outcome:
    s, exc = _occurrence(ctx, p)
    _not_done(ctx, s, exc, p.on_date)
    if exc is not None and exc.started_at and exc.ended_at:
        start, end = exc.started_at, exc.ended_at
    else:
        start, end = planned_times(s, p.on_date)
    start, end = p.started_at or start, p.ended_at or end
    if start > ctx.now:
        raise ActionError(f"{_name(ctx, s)} on {_day(p.on_date)} hasn't started yet")

    logged = log_time(ctx, LogTime(category_id=s.category_id, job=s.job, started_at=start,
                                   ended_at=end, note=p.note or s.title, source="calendar"))
    entry_id = logged.result["time_entry"]["id"]
    step = _set_exception(ctx, s, exc, p.on_date, {"skipped": False, "time_entry_id": entry_id})
    # Undo: unlink first, then remove the entry.
    return Outcome(logged.summary, [step, *logged.inverse], logged.result)


@action("restore_occurrence", RestoreOccurrence, internal=True)
def restore_occurrence(ctx: ActionContext, p: RestoreOccurrence) -> Outcome:
    exc = ctx.session.scalar(select(ScheduleException).where(
        ScheduleException.schedule_id == p.schedule_id, ScheduleException.on_date == p.on_date
    ).with_for_update())
    if p.state is None:
        if exc is not None:
            ctx.session.delete(exc)
    else:
        if exc is None:
            exc = ScheduleException(schedule_id=p.schedule_id, on_date=p.on_date)
            ctx.session.add(exc)
        for key, value in p.state.model_dump().items():
            setattr(exc, key, value)
    ctx.session.flush()
    return Outcome("Restored occurrence", None)  # only ever an inverse
