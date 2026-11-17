from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.actions.common import get_or_404
from app.actions.time_entries import LogTime, StartTimer, TimeEntryPatch
from app.config import JOBS
from app.deps import CtxDep, SessionDep
from app.models import TimeEntry
from app.routers.common import run
from app.schemas import ActionOut, TimeEntryOut
from app.timeutil import AwareDatetime, local_day_bounds, local_today

router = APIRouter(tags=["time"])


class StopBody(BaseModel):
    at: AwareDatetime | None = None


class ClockInBody(BaseModel):
    job: str
    category: str | None = None  # defaults to the job's category in config.JOBS
    note: str | None = None
    at: AwareDatetime | None = None


@router.get("/time-entries", response_model=list[TimeEntryOut])
def list_entries(session: SessionDep, start: date | None = None, end: date | None = None):
    """Entries that started between local dates `start` and `end` (inclusive); default today."""
    start = start or local_today()
    lo, _ = local_day_bounds(start)
    _, hi = local_day_bounds(end or start)
    q = (select(TimeEntry)
         .where(TimeEntry.started_at >= lo, TimeEntry.started_at < hi)
         .order_by(TimeEntry.started_at))
    return session.scalars(q).all()


@router.get("/time-entries/{entry_id}", response_model=TimeEntryOut)
def get_entry(entry_id: int, session: SessionDep):
    return get_or_404(session, TimeEntry, entry_id)


@router.post("/time-entries", status_code=201)
def log_time(body: LogTime, ctx: CtxDep) -> ActionOut:
    return run(ctx, "log_time", body)


@router.patch("/time-entries/{entry_id}")
def update_entry(entry_id: int, body: TimeEntryPatch, ctx: CtxDep) -> ActionOut:
    return run(ctx, "update_time_entry", {"entry_id": entry_id, "fields": body})


@router.delete("/time-entries/{entry_id}")
def delete_entry(entry_id: int, ctx: CtxDep) -> ActionOut:
    return run(ctx, "delete_time_entry", {"entry_id": entry_id})


@router.get("/timer", response_model=TimeEntryOut | None)
def get_timer(session: SessionDep):
    return session.scalar(select(TimeEntry).where(TimeEntry.ended_at.is_(None)))


@router.post("/timer/start")
def start_timer(body: StartTimer, ctx: CtxDep) -> ActionOut:
    return run(ctx, "start_timer", body)


@router.post("/timer/stop")
def stop_timer(ctx: CtxDep, body: StopBody | None = None) -> ActionOut:
    return run(ctx, "stop_timer", body.model_dump(exclude_unset=True) if body else {})


@router.post("/shifts/clock-in")
def clock_in(body: ClockInBody, ctx: CtxDep) -> ActionOut:
    payload = body.model_dump(exclude_unset=True)
    payload.setdefault("category", JOBS.get(body.job))  # unknown job is rejected by the action
    return run(ctx, "start_timer", payload)


@router.post("/shifts/clock-out")
def clock_out(ctx: CtxDep, body: StopBody | None = None) -> ActionOut:
    payload = body.model_dump(exclude_unset=True) if body else {}
    return run(ctx, "stop_timer", {**payload, "require_work": True})
