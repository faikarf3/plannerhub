from datetime import date, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.actions.schedules import CreateSchedule, SchedulePatch
from app.deps import CtxDep, SessionDep
from app.models import Category, Schedule, Task, TimeEntry
from app.routers.common import run
from app.schedule import describe, label, minutes_per_week, occurrences
from app.schemas import ActionOut, OccurrenceOut, ScheduleOut, TaskOut, TimeEntryOut
from app.timeutil import AwareDatetime, local_day_bounds, local_today

router = APIRouter(tags=["schedule"])


class ScheduleView(ScheduleOut):
    label: str
    description: str
    is_work: bool
    minutes_per_week: int
    active: bool  # false once `until` has passed


class SchedulesOut(BaseModel):
    schedules: list[ScheduleView]
    paid_minutes_per_week: int  # active work repeats only


class MoveBody(BaseModel):
    started_at: AwareDatetime
    ended_at: AwareDatetime


class ConfirmBody(BaseModel):
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    note: str | None = None


class CalendarOut(BaseModel):
    start: date
    end: date
    entries: list[TimeEntryOut]
    planned: list[OccurrenceOut]
    tasks: list[TaskOut]  # one-off tasks with a scheduled time


@router.get("/schedules")
def list_schedules(session: SessionDep) -> SchedulesOut:
    today = local_today()
    cats = {c.id: c for c in session.scalars(select(Category))}
    views = []
    for s in session.scalars(select(Schedule).order_by(Schedule.start_time, Schedule.id)):
        cat = cats[s.category_id]
        views.append(ScheduleView(
            **ScheduleOut.model_validate(s).model_dump(), label=label(s, cat),
            description=describe(s), is_work=cat.is_work, minutes_per_week=minutes_per_week(s),
            active=s.until is None or s.until >= today,
        ))
    paid = sum(v.minutes_per_week for v in views if v.is_work and v.active)
    return SchedulesOut(schedules=views, paid_minutes_per_week=paid)


@router.post("/schedules", status_code=201)
def create_schedule(body: CreateSchedule, ctx: CtxDep) -> ActionOut:
    return run(ctx, "create_schedule", body)


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: SchedulePatch, ctx: CtxDep) -> ActionOut:
    return run(ctx, "update_schedule", {"schedule_id": schedule_id, "fields": body})


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, ctx: CtxDep) -> ActionOut:
    return run(ctx, "delete_schedule", {"schedule_id": schedule_id})


@router.post("/schedules/{schedule_id}/occurrences/{on_date}/skip")
def skip(schedule_id: int, on_date: date, ctx: CtxDep) -> ActionOut:
    """Skip one week's occurrence (named by the local date it starts on)."""
    return run(ctx, "skip_occurrence", {"schedule_id": schedule_id, "on_date": on_date})


@router.post("/schedules/{schedule_id}/occurrences/{on_date}/move")
def move(schedule_id: int, on_date: date, body: MoveBody, ctx: CtxDep) -> ActionOut:
    return run(ctx, "move_occurrence",
               {"schedule_id": schedule_id, "on_date": on_date, **body.model_dump()})


@router.post("/schedules/{schedule_id}/occurrences/{on_date}/confirm")
def confirm(schedule_id: int, on_date: date, ctx: CtxDep,
            body: ConfirmBody | None = None) -> ActionOut:
    """Mark a planned occurrence as done: logs it as a time entry (planned times
    unless others are given)."""
    payload = body.model_dump(exclude_none=True) if body else {}
    return run(ctx, "confirm_occurrence",
               {"schedule_id": schedule_id, "on_date": on_date, **payload})


@router.get("/calendar")
def calendar(session: SessionDep, start: date | None = None, end: date | None = None,
             include_skipped: bool = False) -> CalendarOut:
    """Logged time plus planned blocks for local days start..end (inclusive).
    Default: this week, Monday to Sunday."""
    if start is None:
        today = local_today()
        start = today - timedelta(days=today.weekday())
    end = end or start + timedelta(days=6)
    lo, _ = local_day_bounds(start)
    _, hi = local_day_bounds(end)
    entries = session.scalars(select(TimeEntry).where(
        TimeEntry.started_at < hi, (TimeEntry.ended_at.is_(None)) | (TimeEntry.ended_at > lo)
    ).order_by(TimeEntry.started_at))
    tasks = session.scalars(select(Task).where(
        Task.scheduled_start >= lo, Task.scheduled_start < hi, Task.status != "skipped"
    ).order_by(Task.scheduled_start))
    planned = occurrences(session, start, end, include_skipped=include_skipped)
    return CalendarOut(
        start=start, end=end,
        entries=[TimeEntryOut.model_validate(e) for e in entries],
        planned=[OccurrenceOut(**vars(o)) for o in planned],
        tasks=[TaskOut.model_validate(t) for t in tasks],
    )
