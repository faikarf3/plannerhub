from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TASK_STATUSES = ("todo", "doing", "done", "skipped")
TIME_SOURCES = ("timer", "voice", "manual", "calendar", "pipeline")
APPLICATION_STATUSES = ("applied", "oa", "interview", "offer", "rejected", "ghosted")
CONTENT_STATUSES = ("created", "posted", "failed", "missing")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True), dict[str, Any]: JSONB}


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    color: Mapped[str | None] = mapped_column(String(20))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    is_work: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    weekly_target_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status_valid"),
        CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end > scheduled_start",
            name="schedule_order",
        ),
        Index("ix_tasks_status_due", "status", "due_at"),
        Index("ix_tasks_scheduled_start", "scheduled_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(10), server_default="todo")
    due_at: Mapped[datetime | None]
    scheduled_start: Mapped[datetime | None]
    scheduled_end: Mapped[datetime | None]
    recurrence_rule: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), server_default="manual")
    linked_type: Mapped[str | None] = mapped_column(String(30))
    linked_id: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        CheckConstraint(_in("source", TIME_SOURCES), name="source_valid"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="end_after_start"),
        CheckConstraint(
            "(ended_at IS NULL) = (duration_min IS NULL)", name="duration_iff_ended"
        ),
        # ended_at IS NULL means "the running timer"; the DB guarantees at most one.
        Index(
            "uq_time_entries_one_running",
            text("(ended_at IS NULL)"),
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_time_entries_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    job: Mapped[str | None] = mapped_column(String(30))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]
    duration_min: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), server_default="manual")
    confirmed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Climb(Base):
    """Climbing details for a time entry; date and duration live on the entry."""

    __tablename__ = "climbs"

    id: Mapped[int] = mapped_column(primary_key=True)
    time_entry_id: Mapped[int] = mapped_column(
        ForeignKey("time_entries.id", ondelete="CASCADE"), unique=True
    )
    gym: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Schedule(Base):
    """A repeating weekly block ("tutoring every Tue 3-6pm"). Occurrences are
    computed from the rule (app/schedule.py), never stored per week; one-week
    changes are ScheduleException rows. Times are New York wall-clock times; an
    end_time earlier than start_time ends the next day."""

    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("start_time <> end_time", name="nonzero_length"),
        CheckConstraint("until IS NULL OR until >= starts_on", name="until_after_start"),
        CheckConstraint("cardinality(weekdays) > 0", name="has_days"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(100))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    job: Mapped[str | None] = mapped_column(String(30))
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(Integer))  # 0 = Monday
    start_time: Mapped[time]
    end_time: Mapped[time]
    starts_on: Mapped[date]
    until: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ScheduleException(Base):
    """One occurrence (identified by the local date it starts on) that differs
    from its rule: skipped, moved, or confirmed as done (linked time entry)."""

    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        UniqueConstraint("schedule_id", "on_date", name="uq_schedule_exceptions_occurrence"),
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="end_after_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("schedules.id", ondelete="CASCADE"))
    on_date: Mapped[date]
    skipped: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    time_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("time_entries.id", ondelete="SET NULL")
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        CheckConstraint("input_type IN ('voice', 'typed')", name="input_type_valid"),
        CheckConstraint("mood IS NULL OR mood BETWEEN 1 AND 5", name="mood_range"),
        CheckConstraint("energy IS NULL OR energy BETWEEN 1 AND 5", name="energy_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    input_type: Mapped[str] = mapped_column(String(10))
    raw_text: Mapped[str] = mapped_column(Text)
    audio_url: Mapped[str | None] = mapped_column(Text)
    mood: Mapped[int | None] = mapped_column(Integer)
    energy: Mapped[int | None] = mapped_column(Integer)
    # Set when extraction asked instead of guessing: {"question": str, "options": [str]}.
    # Answered via POST /clarify/{id}; a follow-up question replaces it.
    clarify_question: Mapped[dict[str, Any] | None]
    clarify_answer: Mapped[str | None] = mapped_column(Text)


class PipelineKey(Base):
    """A key one pipeline uses to post /events. Only the hash is stored."""

    __tablename__ = "pipeline_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(12))  # first characters, to tell keys apart
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]


class Event(Base):
    """Raw inbox for pipeline webhooks. Like journal entries, these are input, not
    planner changes; what they lead to goes through the action layer."""

    __tablename__ = "events"
    __table_args__ = (
        # The sender's own id makes retries harmless.
        UniqueConstraint("source", "sender_id", name="uq_events_source_sender_id"),
        Index("ix_events_received_at", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    type: Mapped[str] = mapped_column(String(50))
    sender_id: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]]
    occurred_at: Mapped[datetime]
    received_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)


class Application(Base):
    """Job applications, written only from job-tracker events."""

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(_in("status", APPLICATION_STATUSES), name="status_valid"),
        Index("ix_applications_company", func.lower(text("company"))),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="applied")
    applied_at: Mapped[datetime | None]
    replied_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ContentItem(Base):
    """One 3AM Facts night. `missing` is set by the hub when nothing reported."""

    __tablename__ = "content_items"
    __table_args__ = (CheckConstraint(_in("status", CONTENT_STATUSES), name="status_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    posts: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SiSession(Base):
    """One week of SI (PH201): the Monday session and its prep checklist.
    Written only by update_si_session; a week with no row reads as all defaults."""

    __tablename__ = "si_sessions"
    __table_args__ = (
        CheckConstraint("extract(isodow from week_of) = 1", name="week_of_monday"),
        CheckConstraint("attendance IS NULL OR attendance >= 0", name="attendance_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    week_of: Mapped[date] = mapped_column(unique=True)  # the session's Monday (New York)
    topic: Mapped[str | None] = mapped_column(Text)
    plan_form_done: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    slides_done: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    breakdown_done: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    answer_sheet_done: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    session_at: Mapped[datetime | None]
    attendance: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ActionLog(Base):
    """Every change from any input. `inverse` is a list of steps that reverses it."""

    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL")
    )
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"))
    action_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]]
    # [{"action_type": ..., "payload": {...}}, ...]; null = cannot be undone
    inverse: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(server_default=func.now())
    undone_at: Mapped[datetime | None]
