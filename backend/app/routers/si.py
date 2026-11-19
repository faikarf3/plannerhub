from datetime import date

from fastapi import APIRouter

from app.actions.base import ActionError
from app.actions.si import SiSessionPatch, check_monday
from app.deps import CtxDep, SessionDep
from app.routers.common import run
from app.schemas import ActionOut, SiSessionOut
from app.si import current_week
from app.timeutil import utcnow

router = APIRouter(tags=["si"])


class SiWeekOut(SiSessionOut):
    prep_minutes_this_week: int


@router.get("/si-sessions/current")
def get_current(session: SessionDep) -> SiWeekOut:
    """This week's SI plan: today if Monday, else next Monday (New York). With no
    saved row, returns defaults with `id: null` (nothing is written)."""
    week, minutes = current_week(session, utcnow())
    return SiWeekOut(**week.model_dump(), prep_minutes_this_week=minutes)


@router.patch("/si-sessions/{week_of}")
def update_week(week_of: date, body: SiSessionPatch, ctx: CtxDep) -> ActionOut:
    """Create or update that Monday's row; any subset of fields. Undoable."""
    try:
        check_monday(week_of)
    except ValueError as e:
        raise ActionError(str(e)) from e
    return run(ctx, "update_si_session", {"week_of": week_of, "fields": body})
