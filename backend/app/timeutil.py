"""Timestamps are stored in UTC and shown in America/New_York.

Naive datetimes coming in from clients are interpreted as New York local time.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator

LOCAL_TZ = ZoneInfo("America/New_York")


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(UTC)


# Use for every datetime field accepted from clients.
AwareDatetime = Annotated[datetime, AfterValidator(to_utc)]


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_today(now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(LOCAL_TZ).date()


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) of a New York calendar day (DST-safe)."""
    start = datetime.combine(day, time.min, tzinfo=LOCAL_TZ)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def minutes_between(start: datetime, end: datetime) -> int:
    return round((end - start).total_seconds() / 60)


def fmt_local(dt: datetime) -> str:
    """Short human time for summaries, e.g. '2:05pm' or 'Fri 2:05pm' if not today."""
    local = dt.astimezone(LOCAL_TZ)
    clock = local.strftime("%-I:%M%p").lower()
    if local.date() != local_today():
        return f"{local.strftime('%a %b %-d')} {clock}"
    return clock


def fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h}h {m:02d}m"
    return f"{h}h" if h else f"{m}m"
