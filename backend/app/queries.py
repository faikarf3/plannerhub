"""Read-side views: today and the morning digest. No writes here."""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import LONG_TIMER_HOURS
from app.models import Category, Task, TimeEntry
from app.schemas import TaskOut, TimeEntryOut
from app.timeutil import fmt_duration, fmt_local, local_day_bounds, minutes_between

OPEN = ("todo", "doing")


def _categories(session: Session) -> dict[int, Category]:
    return {c.id: c for c in session.scalars(select(Category))}


def _dump(model, rows) -> list[dict]:
    return [model.model_validate(r).model_dump(mode="json") for r in rows]


def _scheduled(session: Session, start: datetime, end: datetime) -> list[Task]:
    return list(session.scalars(
        select(Task)
        .where(Task.scheduled_start >= start, Task.scheduled_start < end, Task.status != "skipped")
        .order_by(Task.scheduled_start)
    ))


def _due(session: Session, end: datetime) -> list[Task]:
    """Open tasks due before `end`, overdue ones included."""
    return list(session.scalars(
        select(Task).where(Task.status.in_(OPEN), Task.due_at < end).order_by(Task.due_at)
    ))


def _entries(session: Session, start: datetime, end: datetime) -> list[TimeEntry]:
    return list(session.scalars(
        select(TimeEntry)
        .where(TimeEntry.started_at >= start, TimeEntry.started_at < end)
        .order_by(TimeEntry.started_at)
    ))


def _running(session: Session) -> TimeEntry | None:
    return session.scalar(select(TimeEntry).where(TimeEntry.ended_at.is_(None)))


def _minutes_by_category(
    entries: list[TimeEntry], cats: dict[int, Category], now: datetime
) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for e in entries:
        totals[cats[e.category_id].name] += e.duration_min or minutes_between(e.started_at, now)
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def today_view(session: Session, day: date, now: datetime) -> dict:
    start, end = local_day_bounds(day)
    cats = _categories(session)
    scheduled = _scheduled(session, start, end)
    entries = _entries(session, start, end)
    running = _running(session)
    return {
        "date": day.isoformat(),
        "tasks_due": _dump(TaskOut, _due(session, end)),
        "scheduled": _dump(TaskOut, [t for t in scheduled if not cats[t.category_id].is_work]),
        "planned_shifts": _dump(TaskOut, [t for t in scheduled if cats[t.category_id].is_work]),
        "running_timer": TimeEntryOut.model_validate(running).model_dump(mode="json")
        if running else None,
        "time_entries": _dump(TimeEntryOut, entries),
        "minutes_by_category": _minutes_by_category(entries, cats, now),
    }


def morning_digest(session: Session, day: date, now: datetime) -> dict:
    """Data for the morning push. Applications and 3AM Facts lines arrive in Phase 5."""
    start, end = local_day_bounds(day)
    y_start, _ = local_day_bounds(day - timedelta(days=1))
    cats = _categories(session)

    due = _due(session, end)
    overdue = [t for t in due if t.due_at < start]
    due_today = [t for t in due if t.due_at >= start]
    shifts = [t for t in _scheduled(session, start, end) if cats[t.category_id].is_work]
    yesterday = [e for e in _entries(session, y_start, start) if e.ended_at is not None]
    y_totals = _minutes_by_category(yesterday, cats, now)
    unconfirmed = sum(1 for e in yesterday if not e.confirmed)
    running = _running(session)

    lines: list[str] = []
    if shifts:
        lines.append("Shifts: " + ", ".join(
            f"{t.title} {fmt_local(t.scheduled_start)}" for t in shifts))
    if due_today:
        lines.append(f"Due today ({len(due_today)}): " + ", ".join(t.title for t in due_today))
    if overdue:
        lines.append(f"Overdue ({len(overdue)}): " + ", ".join(t.title for t in overdue))
    if y_totals:
        lines.append("Yesterday: " + ", ".join(
            f"{name} {fmt_duration(m)}" for name, m in y_totals.items()))
    if unconfirmed:
        lines.append(f"{unconfirmed} estimated entr{'y' if unconfirmed == 1 else 'ies'} to confirm")
    long_timer = False
    if running:
        ran = minutes_between(running.started_at, now)
        long_timer = ran >= LONG_TIMER_HOURS * 60
        label = running.job or cats[running.category_id].name
        lines.append(f"{'⚠️ ' if long_timer else ''}Timer running: {label} for {fmt_duration(ran)}")

    return {
        "date": day.isoformat(),
        "planned_shifts": _dump(TaskOut, shifts),
        "due_today": _dump(TaskOut, due_today),
        "overdue": _dump(TaskOut, overdue),
        "yesterday_minutes_by_category": y_totals,
        "yesterday_unconfirmed": unconfirmed,
        "running_timer": TimeEntryOut.model_validate(running).model_dump(mode="json")
        if running else None,
        "long_running_timer": long_timer,
        "text": "\n".join(lines) or "Nothing scheduled today.",
    }
