from datetime import date

from fastapi import APIRouter
from sqlalchemy import select

from app.actions import undo_action
from app.actions.categories import CreateCategory
from app.deps import CtxDep, SessionDep
from app.models import ActionLog, Category
from app.queries import morning_digest, today_view
from app.routers.common import run
from app.schemas import ActionLogOut, ActionOut, CategoryOut
from app.timeutil import local_today, utcnow

router = APIRouter()


def _log_out(entry: ActionLog) -> ActionLogOut:
    return ActionLogOut(
        id=entry.id, journal_entry_id=entry.journal_entry_id, event_id=entry.event_id,
        action_type=entry.action_type,
        summary=entry.summary, payload=entry.payload,
        undoable=entry.inverse is not None and entry.undone_at is None,
        applied_at=entry.applied_at, undone_at=entry.undone_at,
    )


@router.get("/actions", tags=["actions"])
def list_actions(session: SessionDep, limit: int = 50) -> list[ActionLogOut]:
    rows = session.scalars(select(ActionLog).order_by(ActionLog.id.desc()).limit(limit))
    return [_log_out(r) for r in rows]


@router.post("/actions/{action_id}/undo", tags=["actions"])
def undo(action_id: int, ctx: CtxDep) -> ActionLogOut:
    return _log_out(undo_action(ctx, action_id))


@router.get("/categories", response_model=list[CategoryOut], tags=["categories"])
def list_categories(session: SessionDep):
    return session.scalars(select(Category).order_by(Category.id)).all()


@router.post("/categories", status_code=201, tags=["categories"])
def create_category(body: CreateCategory, ctx: CtxDep) -> ActionOut:
    return run(ctx, "create_category", body)


@router.get("/today", tags=["views"])
def today(session: SessionDep, day: date | None = None) -> dict:
    return today_view(session, day or local_today(), utcnow())


@router.get("/digest/morning", tags=["views"])
def digest(session: SessionDep, day: date | None = None) -> dict:
    return morning_digest(session, day or local_today(), utcnow())
