"""Read models. Also used as undo snapshots: a deleted row's `*Out` dump is the
payload of its restore action, so the two can never drift apart."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.timeutil import AwareDatetime as UtcDatetime  # always serialized in UTC


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CategoryOut(_Orm):
    id: int
    name: str
    color: str | None
    parent_id: int | None
    is_work: bool
    weekly_target_hours: Decimal | None


class TaskOut(_Orm):
    id: int
    title: str
    category_id: int
    status: str
    due_at: UtcDatetime | None
    scheduled_start: UtcDatetime | None
    scheduled_end: UtcDatetime | None
    recurrence_rule: str | None
    source: str
    linked_type: str | None
    linked_id: int | None
    completed_at: UtcDatetime | None


class TimeEntryOut(_Orm):
    id: int
    category_id: int
    task_id: int | None
    job: str | None
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    duration_min: int | None
    source: str
    confirmed: bool
    note: str | None


class ClimbOut(_Orm):
    id: int
    time_entry_id: int
    gym: str | None
    notes: str | None


class ActionOut(BaseModel):
    """One line on a confirmation card."""

    action_id: int
    action_type: str
    summary: str
    result: dict


class ActionLogOut(_Orm):
    id: int
    journal_entry_id: int | None
    action_type: str
    summary: str
    payload: dict
    undoable: bool
    applied_at: UtcDatetime
    undone_at: UtcDatetime | None
