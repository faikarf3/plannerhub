"""Expanding repeating schedules into dated occurrences. Read-only.

An occurrence is named by its schedule and the local date it starts on. Its
times come from the rule (New York wall clock, so DST moves nothing), unless a
ScheduleException moves, skips or confirms it.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import JOB_LABELS
from app.models import Category, Schedule, ScheduleException
from app.timeutil import LOCAL_TZ, local_day_bounds

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Occurrence:
    schedule_id: int
    on_date: date
    started_at: datetime
    ended_at: datetime
    label: str
    category_id: int
    job: str | None
    is_work: bool
    status: Literal["planned", "skipped", "done"]
    moved: bool
    time_entry_id: int | None


def label(s: Schedule, category: Category) -> str:
    return s.title or (JOB_LABELS.get(s.job, s.job) if s.job else category.name)


def occurs_on(s: Schedule, day: date) -> bool:
    return (day.weekday() in s.weekdays and s.starts_on <= day
            and (s.until is None or day <= s.until))


def planned_times(s: Schedule, day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, s.start_time, tzinfo=LOCAL_TZ)
    end_day = day if s.end_time > s.start_time else day + timedelta(days=1)  # overnight
    end = datetime.combine(end_day, s.end_time, tzinfo=LOCAL_TZ)
    return start, end


def minutes_per_week(s: Schedule) -> int:
    start, end = planned_times(s, date(2026, 1, 5))  # any non-DST-change Monday
    return len(set(s.weekdays)) * round((end - start).total_seconds() / 60)


def describe(s: Schedule) -> str:
    """'Tue, Thu 3:00pm-6:00pm' for summaries."""
    days = ", ".join(DAY_NAMES[d] for d in sorted(set(s.weekdays)))

    def clock(t):
        return t.strftime("%-I:%M%p").lower()

    return f"{days} {clock(s.start_time)}–{clock(s.end_time)}"


def occurrences(
    session: Session, first: date, last: date, *, include_skipped: bool = False
) -> list[Occurrence]:
    """Occurrences overlapping local days first..last (inclusive), by start time.
    Starts the day before `first` too, so an overnight shift shows on both days."""
    lo, _ = local_day_bounds(first)
    _, hi = local_day_bounds(last)
    begin = first - timedelta(days=1)
    rules = list(session.scalars(select(Schedule).where(
        Schedule.starts_on <= last, or_(Schedule.until.is_(None), Schedule.until >= begin))))
    if not rules:
        return []
    cats = {c.id: c for c in session.scalars(select(Category))}
    exceptions = {
        (e.schedule_id, e.on_date): e
        for e in session.scalars(select(ScheduleException).where(
            ScheduleException.schedule_id.in_([s.id for s in rules]),
            ScheduleException.on_date >= begin, ScheduleException.on_date <= last))
    }

    out: list[Occurrence] = []
    day = begin
    while day <= last:
        for s in rules:
            if not occurs_on(s, day):
                continue
            exc = exceptions.get((s.id, day))
            start, end = planned_times(s, day)
            moved = bool(exc and exc.started_at and exc.ended_at)
            if moved:
                start, end = exc.started_at, exc.ended_at
            status = ("done" if exc and exc.time_entry_id else
                      "skipped" if exc and exc.skipped else "planned")
            if status == "skipped" and not include_skipped:
                continue
            if end <= lo or start >= hi:
                continue
            cat = cats[s.category_id]
            out.append(Occurrence(
                schedule_id=s.id, on_date=day, started_at=start, ended_at=end,
                label=label(s, cat), category_id=s.category_id, job=s.job,
                is_work=cat.is_work, status=status, moved=moved,
                time_entry_id=exc.time_entry_id if exc else None,
            ))
        day += timedelta(days=1)
    out.sort(key=lambda o: o.started_at)
    return out
