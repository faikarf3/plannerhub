from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.actions.pipelines import CreatePipelineKey
from app.deps import CtxDep, PipelineSourceDep, SessionDep
from app.models import Application, ContentItem, Event, PipelineKey
from app.pipelines import EventIn, EventResult, check_missing, handle_event
from app.routers.common import run
from app.schemas import (
    ActionOut,
    ApplicationOut,
    ContentItemOut,
    EventOut,
    PipelineKeyOut,
)

# POST /events authenticates with a pipeline key (see deps.pipeline_source);
# everything else here uses the owner token like the rest of the API.
ingest = APIRouter(tags=["pipelines"])
router = APIRouter(tags=["pipelines"])


class EventResponse(BaseModel):
    event_id: int
    duplicate: bool
    actions: list[ActionOut]
    error: str | None
    message: str


class CheckOut(BaseModel):
    actions: list[ActionOut]
    message: str


def _actions(applied) -> list[ActionOut]:
    return [ActionOut(**vars(a)) for a in applied]


def _event_out(result: EventResult) -> EventResponse:
    actions = _actions(result.actions)
    if result.duplicate:
        message = f"already received as event {result.event_id}; ignored"
    elif result.error:
        message = "\n".join([*(a.summary for a in actions), f"Stopped: {result.error}"])
    else:
        message = "\n".join(a.summary for a in actions) or "recorded"
    return EventResponse(event_id=result.event_id, duplicate=result.duplicate, actions=actions,
                         error=result.error, message=message)


@ingest.post("/events")
def post_event(body: EventIn, source: PipelineSourceDep, ctx: CtxDep) -> EventResponse:
    """A pipeline reports something that happened. Refused (422) if the type or
    data is wrong; otherwise stored, then reacted to."""
    return _event_out(handle_event(ctx, source, body))


@router.get("/events", response_model=list[EventOut])
def list_events(session: SessionDep, source: str | None = None, limit: int = 50):
    q = select(Event).order_by(Event.id.desc()).limit(min(limit, 500))
    if source:
        q = q.where(Event.source == source)
    return session.scalars(q).all()


@router.post("/pipelines/check")
def run_checks(ctx: CtxDep) -> CheckOut:
    """For Cloud Scheduler each morning: flags a 3AM Facts night that never reported."""
    actions = _actions(check_missing(ctx))
    return CheckOut(actions=actions,
                    message="\n".join(a.summary for a in actions) or "nothing missing")


@router.get("/pipeline-keys", response_model=list[PipelineKeyOut])
def list_keys(session: SessionDep):
    return session.scalars(select(PipelineKey).order_by(PipelineKey.id)).all()


@router.post("/pipeline-keys", status_code=201)
def create_key(body: CreatePipelineKey, ctx: CtxDep) -> ActionOut:
    """The new key is in `result.key`. It's shown only this once."""
    return run(ctx, "create_pipeline_key", body)


@router.delete("/pipeline-keys/{key_id}")
def revoke_key(key_id: int, ctx: CtxDep) -> ActionOut:
    return run(ctx, "revoke_pipeline_key", {"key_id": key_id})


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(session: SessionDep, status: str | None = None, limit: int = 200):
    q = select(Application).order_by(Application.id.desc()).limit(min(limit, 1000))
    if status:
        q = q.where(Application.status == status)
    return session.scalars(q).all()


@router.get("/content", response_model=list[ContentItemOut])
def list_content(session: SessionDep, limit: int = 14):
    q = select(ContentItem).order_by(ContentItem.run_date.desc()).limit(min(limit, 366))
    return session.scalars(q).all()
