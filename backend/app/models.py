from datetime import datetime
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TASK_STATUSES = ("todo", "doing", "done", "skipped")
TIME_SOURCES = ("timer", "voice", "manual", "calendar", "pipeline")


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


class ActionLog(Base):
    """Every change from any input. `inverse` is a list of steps that reverses it."""

    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="SET NULL")
    )
    action_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]]
    # [{"action_type": ..., "payload": {...}}, ...]; null = cannot be undone
    inverse: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(server_default=func.now())
    undone_at: Mapped[datetime | None]
