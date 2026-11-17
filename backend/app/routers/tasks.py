from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.actions.common import get_or_404
from app.actions.tasks import CreateTask, TaskPatch, TaskStatus
from app.deps import CtxDep, SessionDep
from app.models import Task
from app.routers.common import run
from app.schemas import ActionOut, TaskOut
from app.timeutil import AwareDatetime

router = APIRouter(prefix="/tasks", tags=["tasks"])


class CompleteBody(BaseModel):
    completed_at: AwareDatetime | None = None


@router.get("", response_model=list[TaskOut])
def list_tasks(
    session: SessionDep,
    status: TaskStatus | None = None,
    category_id: int | None = None,
    limit: int = 200,
):
    q = select(Task).order_by(Task.due_at.nulls_last(), Task.id).limit(limit)
    if status:
        q = q.where(Task.status == status)
    if category_id:
        q = q.where(Task.category_id == category_id)
    return session.scalars(q).all()


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, session: SessionDep):
    return get_or_404(session, Task, task_id)


@router.post("", status_code=201)
def create_task(body: CreateTask, ctx: CtxDep) -> ActionOut:
    return run(ctx, "create_task", body)


@router.patch("/{task_id}")
def update_task(task_id: int, body: TaskPatch, ctx: CtxDep) -> ActionOut:
    return run(ctx, "update_task", {"task_id": task_id, "fields": body})


@router.post("/{task_id}/complete")
def complete_task(task_id: int, ctx: CtxDep, body: CompleteBody | None = None) -> ActionOut:
    payload = {"task_id": task_id, **(body.model_dump(exclude_unset=True) if body else {})}
    return run(ctx, "complete_task", payload)


@router.delete("/{task_id}")
def delete_task(task_id: int, ctx: CtxDep) -> ActionOut:
    return run(ctx, "delete_task", {"task_id": task_id})
