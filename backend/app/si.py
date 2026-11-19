"""Read side of the SI weekly plan (also used by GET /projects)."""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SiSession, TimeEntry
from app.schemas import SiSessionOut
from app.timeutil import local_day_bounds, local_today, minutes_between

PREP_JOB = "si_prep"


def current_week_of(today: date) -> date:
    """Today if it's Monday, otherwise next Monday."""
    return today + timedelta(days=(7 - today.weekday()) % 7)


def week_or_defaults(session: Session, week_of: date) -> SiSessionOut:
    row = session.scalar(select(SiSession).where(SiSession.week_of == week_of))
    if row is not None:
        return SiSessionOut.model_validate(row)
    return SiSessionOut(
        id=None, week_of=week_of, topic=None, plan_form_done=False, slides_done=False,
        breakdown_done=False, answer_sheet_done=False, session_at=None, attendance=None,
    )


def prep_minutes(session: Session, week_of: date, now: datetime) -> int:
    """SI prep logged in the 7 New York days before the session's Monday
    ([Monday - 7 days, Monday)). A running prep timer counts up to now."""
    start, _ = local_day_bounds(week_of - timedelta(days=7))
    end, _ = local_day_bounds(week_of)
    entries = session.scalars(
        select(TimeEntry).where(
            TimeEntry.job == PREP_JOB,
            TimeEntry.started_at >= start, TimeEntry.started_at < end,
        )
    )
    total = 0
    for e in entries:
        total += e.duration_min if e.duration_min is not None else max(
            0, minutes_between(e.started_at, min(now, end)))
    return total


def current_week(session: Session, now: datetime) -> tuple[SiSessionOut, int]:
    week_of = current_week_of(local_today(now))
    return week_or_defaults(session, week_of), prep_minutes(session, week_of, now)
