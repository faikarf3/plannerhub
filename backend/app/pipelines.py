"""POST /events: store the raw event, then react through the action layer.

Each (source, type) has a model for its `data` and a reactor that turns it into
actions. Reactions are applied with `event_id` so action_log points back at the
event, and each one can be undone like any other change. See the spec's
"Integrations" section for the contract the pipelines follow.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.actions.base import ActionContext, ActionError, AppliedAction, apply_action
from app.config import FACTS_CATEGORY, FACTS_REPORT_BY_HOUR, JOB_SEARCH_CATEGORY, PIPELINES
from app.models import ContentItem, Event
from app.timeutil import LOCAL_TZ, AwareDatetime

logger = logging.getLogger("planner.events")


class EventIn(BaseModel):
    """What a pipeline posts. `source` may be left out when the key implies it."""

    source: str | None = None
    type: str = Field(min_length=1, max_length=50)
    # The sender's own id for this event; a repeat with the same id is ignored.
    id: str | None = Field(default=None, max_length=200)
    occurred_at: AwareDatetime | None = None
    data: dict[str, Any] = {}


@dataclass
class EventResult:
    event_id: int
    duplicate: bool = False
    actions: list[AppliedAction] = field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------- event data


class _Data(BaseModel):
    model_config = {"extra": "allow"}  # pipelines may send more; it stays in the payload


class VideoCreated(_Data):
    title: str = Field(min_length=1)
    url: str | None = None
    run_date: date | None = None


class Posted(_Data):
    platform: str = Field(min_length=1, max_length=40)
    url: str | None = None
    title: str | None = None
    run_date: date | None = None


class FactsFailed(_Data):
    step: str | None = None
    error: str | None = None
    run_date: date | None = None


class ApplicationSubmitted(_Data):
    company: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    url: str | None = None


class ReplyReceived(_Data):
    company: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    kind: Literal["rejection", "oa", "interview", "offer"]
    deadline: AwareDatetime | None = None


class RunFinished(_Data):
    count: int | None = Field(default=None, ge=0)


class TrackerFailed(_Data):
    error: str | None = None


# ---------------------------------------------------------------- reactions

Apply = Callable[[str, dict[str, Any]], AppliedAction]


def _tonight(at: datetime) -> datetime:
    """23:59 local on the day of `at`: the due time for "fix it today" tasks."""
    return datetime.combine(at.astimezone(LOCAL_TZ).date(), time(23, 59), tzinfo=LOCAL_TZ)


def _run_date(d: BaseModel, at: datetime) -> date:
    return getattr(d, "run_date", None) or at.astimezone(LOCAL_TZ).date()


def _video_created(apply: Apply, d: VideoCreated, at: datetime) -> None:
    apply("save_content_item", {"run_date": _run_date(d, at), "status": "created",
                                "title": d.title, "url": d.url})


def _posted(apply: Apply, d: Posted, at: datetime) -> None:
    apply("save_content_item", {"run_date": _run_date(d, at), "status": "posted",
                                "platform": d.platform, "post_url": d.url, "title": d.title})


def _facts_failed(apply: Apply, d: FactsFailed, at: datetime) -> None:
    error = ": ".join(x for x in (d.step, d.error) if x) or "no details"
    saved = apply("save_content_item", {"run_date": _run_date(d, at), "status": "failed",
                                        "error": error})
    title = f"Fix 3AM Facts run ({d.step} failed)" if d.step else "Fix 3AM Facts run"
    apply("create_task", {"title": title, "category": FACTS_CATEGORY, "due_at": _tonight(at),
                          "source": "pipeline", "linked_type": "content_item",
                          "linked_id": saved.result["content_item"]["id"]})


def _application_submitted(apply: Apply, d: ApplicationSubmitted, at: datetime) -> None:
    apply("save_application", {"company": d.company, "role": d.role, "url": d.url,
                               "status": "applied", "applied_at": at})


_REPLY_STATUS = {"rejection": "rejected", "oa": "oa", "interview": "interview", "offer": "offer"}
_REPLY_TASK = {"oa": "online assessment", "interview": "interview", "offer": "respond to offer"}


def _reply_received(apply: Apply, d: ReplyReceived, at: datetime) -> None:
    saved = apply("save_application", {"company": d.company, "role": d.role,
                                       "status": _REPLY_STATUS[d.kind], "replied_at": at})
    if d.kind in _REPLY_TASK:
        task: dict[str, Any] = {
            # The stored spelling, not however this reply happened to write it.
            "title": f"{saved.result['application']['company']}: {_REPLY_TASK[d.kind]}",
            "category": JOB_SEARCH_CATEGORY,
            "source": "pipeline", "linked_type": "application",
            "linked_id": saved.result["application"]["id"],
        }
        if d.deadline:
            task["due_at"] = d.deadline
        apply("create_task", task)


def _run_finished(apply: Apply, d: RunFinished, at: datetime) -> None:
    """Heartbeat only: the stored event is what proves the tracker ran."""


def _tracker_failed(apply: Apply, d: TrackerFailed, at: datetime) -> None:
    apply("create_task", {"title": "Fix job tracker run", "category": JOB_SEARCH_CATEGORY,
                          "due_at": _tonight(at), "source": "pipeline"})


HANDLERS: dict[tuple[str, str], tuple[type[_Data], Callable[..., None]]] = {
    ("3am_facts", "video_created"): (VideoCreated, _video_created),
    ("3am_facts", "posted"): (Posted, _posted),
    ("3am_facts", "run_failed"): (FactsFailed, _facts_failed),
    ("job_tracker", "application_submitted"): (ApplicationSubmitted, _application_submitted),
    ("job_tracker", "reply_received"): (ReplyReceived, _reply_received),
    ("job_tracker", "run_finished"): (RunFinished, _run_finished),
    ("job_tracker", "run_failed"): (TrackerFailed, _tracker_failed),
}
assert {(s, t) for s, types in PIPELINES.items() for t in types} == set(HANDLERS)


# ---------------------------------------------------------------- entry points


def _validate(source: str, body: EventIn) -> _Data:
    if (source, body.type) not in HANDLERS:
        expected = ", ".join(sorted(PIPELINES[source]))
        raise ActionError(f"{source} doesn't send {body.type!r}; expected one of: {expected}")
    model = HANDLERS[(source, body.type)][0]
    try:
        return model.model_validate(body.data)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'data'}: {err['msg']}"
                             for err in e.errors(include_url=False))
        raise ActionError(f"bad {body.type} data: {problems}") from e


def handle_event(ctx: ActionContext, key_source: str | None, body: EventIn) -> EventResult:
    """`key_source` is the pipeline the key belongs to (None = the owner's token,
    which may post for any source)."""
    source = body.source or key_source
    if source is None:
        raise ActionError("source is required when posting with the owner token")
    if source not in PIPELINES:
        raise ActionError(f"unknown source {source!r}; expected one of {sorted(PIPELINES)}")
    if key_source is not None and source != key_source:
        raise ActionError(f"this key belongs to {key_source}, not {source}", 403)
    data = _validate(source, body)  # a malformed event is refused, not stored

    if body.id is not None:
        seen = ctx.session.scalar(
            select(Event).where(Event.source == source, Event.sender_id == body.id)
        )
        if seen is not None:
            return EventResult(seen.id, duplicate=True, error=seen.error)

    at = body.occurred_at or ctx.now
    event = Event(source=source, type=body.type, sender_id=body.id,
                  payload=body.data, occurred_at=at, received_at=ctx.now)
    ctx.session.add(event)
    ctx.session.flush()

    result = EventResult(event.id)

    def apply(action_type: str, payload: dict[str, Any]) -> AppliedAction:
        applied = apply_action(ctx, action_type, payload, event_id=event.id)
        result.actions.append(applied)
        return applied

    try:
        HANDLERS[(source, body.type)][1](apply, data, at)
    except ActionError as e:
        result.error = e.message
    event.processed_at = ctx.now
    event.error = result.error
    logger.log(logging.WARNING if result.error else logging.INFO,
               "event=%s source=%s type=%s actions=%s error=%s", event.id, source, body.type,
               ",".join(f"{a.action_type}#{a.action_id}" for a in result.actions) or "-",
               result.error or "-")
    return result


def check_missing(ctx: ActionContext) -> list[AppliedAction]:
    """Run each morning (Cloud Scheduler): a night with nothing from 3AM Facts by
    FACTS_REPORT_BY_HOUR is marked missing and gets a task. Safe to repeat."""
    local = ctx.now.astimezone(LOCAL_TZ)
    if local.hour < FACTS_REPORT_BY_HOUR:
        return []
    night = local.date()
    if ctx.session.scalar(select(ContentItem.id).where(ContentItem.run_date == night)):
        return []
    saved = apply_action(ctx, "save_content_item", {"run_date": night, "status": "missing"})
    task = apply_action(ctx, "create_task", {
        "title": "3AM Facts didn't report last night", "category": FACTS_CATEGORY,
        "due_at": _tonight(ctx.now), "source": "pipeline", "linked_type": "content_item",
        "linked_id": saved.result["content_item"]["id"],
    })
    logger.warning("missing 3am_facts run for %s", night)
    return [saved, task]
