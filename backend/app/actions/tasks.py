from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import get_or_404, resolve_category, set_fields
from app.models import Task, TimeEntry
from app.schemas import TaskOut
from app.timeutil import AwareDatetime, fmt_local

TaskStatus = Literal["todo", "doing", "done", "skipped"]


class CreateTask(BaseModel):
    title: str = Field(min_length=1)
    category: str | None = None
    category_id: int | None = None
    status: TaskStatus = "todo"
    due_at: AwareDatetime | None = None
    scheduled_start: AwareDatetime | None = None
    scheduled_end: AwareDatetime | None = None
    recurrence_rule: str | None = None
    source: str = "manual"
    linked_type: str | None = None
    linked_id: int | None = None

    @model_validator(mode="after")
    def _schedule_order(self) -> Self:
        start, end = self.scheduled_start, self.scheduled_end
        if start and end and end <= start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class TaskPatch(BaseModel):
    """Fields a client may change. Explicit nulls clear a field."""

    title: str | None = Field(default=None, min_length=1)
    category: str | None = None
    category_id: int | None = None
    status: TaskStatus | None = None
    due_at: AwareDatetime | None = None
    scheduled_start: AwareDatetime | None = None
    scheduled_end: AwareDatetime | None = None
    recurrence_rule: str | None = None


class UpdateTask(BaseModel):
    task_id: int
    fields: TaskPatch


class CompleteTask(BaseModel):
    task_id: int
    completed_at: AwareDatetime | None = None


class TaskRef(BaseModel):
    task_id: int


class TaskFieldValues(BaseModel):
    """Raw column values; used by inverses to restore exactly what was there."""

    title: str | None = None
    category_id: int | None = None
    status: TaskStatus | None = None
    due_at: AwareDatetime | None = None
    scheduled_start: AwareDatetime | None = None
    scheduled_end: AwareDatetime | None = None
    recurrence_rule: str | None = None
    completed_at: AwareDatetime | None = None


class RestoreTaskFields(BaseModel):
    task_id: int
    values: TaskFieldValues


class RestoreTask(BaseModel):
    task: TaskOut
    time_entry_ids: list[int] = []


def _restore_fields_step(task_id: int, before: dict) -> Step:
    return Step("restore_task_fields", {"task_id": task_id, "values": before})


def _result(task: Task) -> dict:
    return {"task": TaskOut.model_validate(task).model_dump(mode="json")}


@action("create_task", CreateTask)
def create_task(ctx: ActionContext, p: CreateTask) -> Outcome:
    category = resolve_category(ctx.session, p.category, p.category_id)
    task = Task(
        **p.model_dump(exclude={"category", "category_id"}),
        category_id=category.id,
        completed_at=ctx.now if p.status == "done" else None,
    )
    ctx.session.add(task)
    ctx.session.flush()

    summary = f'Added task "{task.title}" ({category.name})'
    if task.due_at:
        summary += f", due {fmt_local(task.due_at)}"
    elif task.scheduled_start:
        summary += f", {fmt_local(task.scheduled_start)}"
    return Outcome(summary, [Step("delete_task", {"task_id": task.id})], _result(task))


@action("update_task", UpdateTask)
def update_task(ctx: ActionContext, p: UpdateTask) -> Outcome:
    task = get_or_404(ctx.session, Task, p.task_id, lock=True)
    patch = p.fields.model_dump(exclude_unset=True)
    if not patch:
        raise ActionError("update_task needs at least one field")

    if "category" in patch or "category_id" in patch:
        category = resolve_category(ctx.session, patch.pop("category", None),
                                    patch.pop("category_id", None))
        patch["category_id"] = category.id
    if "status" in patch and patch["status"] != task.status:
        patch["completed_at"] = ctx.now if patch["status"] == "done" else None
    if "title" in patch and patch["title"] is None:
        raise ActionError("title cannot be cleared")

    before = set_fields(task, patch, TaskOut)
    changed = ", ".join(k for k in patch if k != "completed_at")
    return Outcome(
        f'Updated "{task.title}": {changed}',
        [_restore_fields_step(task.id, before)],
        _result(task),
    )


@action("complete_task", CompleteTask)
def complete_task(ctx: ActionContext, p: CompleteTask) -> Outcome:
    task = get_or_404(ctx.session, Task, p.task_id, lock=True)
    if task.status == "done":
        raise ActionError(f'"{task.title}" is already done', 409)
    done = {"status": "done", "completed_at": p.completed_at or ctx.now}
    before = set_fields(task, done, TaskOut)
    return Outcome(f'Done: "{task.title}"', [_restore_fields_step(task.id, before)], _result(task))


@action("delete_task", TaskRef)
def delete_task(ctx: ActionContext, p: TaskRef) -> Outcome:
    task = get_or_404(ctx.session, Task, p.task_id, lock=True)
    snapshot = TaskOut.model_validate(task).model_dump(mode="json")
    # Time entries keep existing (FK is SET NULL); remember the links so undo can restore them.
    entry_ids = list(ctx.session.scalars(select(TimeEntry.id).where(TimeEntry.task_id == task.id)))
    ctx.session.delete(task)
    ctx.session.flush()
    ctx.session.expire_all()
    return Outcome(
        f'Deleted task "{snapshot["title"]}"',
        [Step("restore_task", {"task": snapshot, "time_entry_ids": entry_ids})],
    )


@action("restore_task", RestoreTask, internal=True)
def restore_task(ctx: ActionContext, p: RestoreTask) -> Outcome:
    if ctx.session.get(Task, p.task.id) is not None:
        raise ActionError(f"task {p.task.id} already exists", 409)
    task = Task(**p.task.model_dump())
    ctx.session.add(task)
    ctx.session.flush()
    if p.time_entry_ids:
        ctx.session.execute(
            update(TimeEntry)
            .where(TimeEntry.id.in_(p.time_entry_ids), TimeEntry.task_id.is_(None))
            .values(task_id=task.id)
        )
    return Outcome(f'Restored task "{task.title}"', [Step("delete_task", {"task_id": task.id})])


@action("restore_task_fields", RestoreTaskFields, internal=True)
def restore_task_fields(ctx: ActionContext, p: RestoreTaskFields) -> Outcome:
    task = get_or_404(ctx.session, Task, p.task_id, lock=True)
    before = set_fields(task, p.values.model_dump(exclude_unset=True), TaskOut)
    return Outcome(f'Restored "{task.title}"', [_restore_fields_step(task.id, before)])
