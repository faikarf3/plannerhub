from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.actions.climbs import LogClimb
from app.config import CLIMBING_CATEGORY
from app.deps import CtxDep, SessionDep
from app.models import Category, Climb, TimeEntry
from app.routers.common import run
from app.schemas import ActionOut, TimeEntryOut
from app.timeutil import local_day_bounds, local_today

router = APIRouter(tags=["climbs"])


class ClimbSession(BaseModel):
    """A climbing time entry with its details (gym/notes are null when none were
    saved, e.g. a plain timer)."""

    time_entry: TimeEntryOut
    climb_id: int | None
    gym: str | None
    notes: str | None


@router.get("/climbs", response_model=list[ClimbSession])
def list_climbs(session: SessionDep, start: date | None = None, end: date | None = None):
    """Climbing sessions that started between local dates `start` and `end`
    (inclusive); default the last 30 days."""
    end = end or local_today()
    start = start or date.fromordinal(end.toordinal() - 29)
    lo, _ = local_day_bounds(start)
    _, hi = local_day_bounds(end)
    rows = session.execute(
        select(TimeEntry, Climb)
        .join(Category, Category.id == TimeEntry.category_id)
        .outerjoin(Climb, Climb.time_entry_id == TimeEntry.id)
        .where(func.lower(Category.name) == CLIMBING_CATEGORY.lower(),
               TimeEntry.started_at >= lo, TimeEntry.started_at < hi)
        .order_by(TimeEntry.started_at.desc())
    )
    return [
        ClimbSession(time_entry=TimeEntryOut.model_validate(entry),
                     climb_id=climb.id if climb else None,
                     gym=climb.gym if climb else None, notes=climb.notes if climb else None)
        for entry, climb in rows
    ]


@router.post("/climbs", status_code=201)
def log_climb(body: LogClimb, ctx: CtxDep) -> ActionOut:
    return run(ctx, "log_climb", body)
