"""Action layer: the only code path that writes to the database.

Every input (manual forms, quick-add, Claude tool calls, pipelines) calls
`apply_action`. Each handler returns an `Outcome` whose `inverse` is a list of
steps (other actions, often internal ones) that reverse it. `apply_action`
records the action and its inverse in `action_log`; `undo_action` replays the
inverse.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ActionLog


class ActionError(Exception):
    """A rejected action. `status` maps straight to the HTTP response code."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class ActionContext:
    session: Session
    now: datetime


@dataclass
class Step:
    action_type: str
    payload: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {"action_type": self.action_type, "payload": self.payload}


@dataclass
class Outcome:
    summary: str
    inverse: list[Step] | None  # None = not undoable
    result: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[ActionContext, Any], Outcome]


@dataclass
class ActionDef:
    name: str
    params: type[BaseModel]
    handler: Handler
    # Internal actions exist to serve as inverses; they are not exposed as
    # Claude tools or quick-add commands.
    internal: bool


REGISTRY: dict[str, ActionDef] = {}


def action(name: str, params: type[BaseModel], *, internal: bool = False):
    def register(fn: Handler) -> Handler:
        if name in REGISTRY:
            raise RuntimeError(f"duplicate action {name}")
        REGISTRY[name] = ActionDef(name, params, fn, internal)
        return fn

    return register


@dataclass
class AppliedAction:
    action_id: int
    action_type: str
    summary: str
    result: dict[str, Any]


def _parse(defn: ActionDef, payload: BaseModel | dict[str, Any]) -> BaseModel:
    if isinstance(payload, defn.params):
        return payload
    raw = payload.model_dump(exclude_unset=True) if isinstance(payload, BaseModel) else payload
    try:
        return defn.params.model_validate(raw)
    except ValidationError as e:
        raise ActionError(f"invalid {defn.name}: {e.errors(include_url=False)}") from e


def _run(ctx: ActionContext, defn: ActionDef, params: BaseModel) -> Outcome:
    """Run a handler inside a savepoint so a failed action leaves no partial writes."""
    try:
        with ctx.session.begin_nested():
            outcome = defn.handler(ctx, params)
            ctx.session.flush()
    except IntegrityError as e:
        raise ActionError(f"{defn.name} conflicts with existing data: {e.orig}", 409) from e
    return outcome


def apply_action(
    ctx: ActionContext,
    action_type: str,
    payload: BaseModel | dict[str, Any],
    *,
    journal_entry_id: int | None = None,
    event_id: int | None = None,
) -> AppliedAction:
    defn = REGISTRY.get(action_type)
    if defn is None:
        raise ActionError(f"unknown action {action_type}", 400)
    params = _parse(defn, payload)
    outcome = _run(ctx, defn, params)

    entry = ActionLog(
        journal_entry_id=journal_entry_id,
        event_id=event_id,
        action_type=action_type,
        payload=params.model_dump(mode="json", exclude_unset=True),
        inverse=None if outcome.inverse is None else [s.to_json() for s in outcome.inverse],
        summary=outcome.summary,
        applied_at=ctx.now,
    )
    ctx.session.add(entry)
    ctx.session.flush()
    return AppliedAction(entry.id, action_type, outcome.summary, outcome.result)


def undo_action(ctx: ActionContext, action_id: int) -> ActionLog:
    entry = ctx.session.scalar(
        select(ActionLog).where(ActionLog.id == action_id).with_for_update()
    )
    if entry is None:
        raise ActionError(f"action {action_id} not found", 404)
    if entry.undone_at is not None:
        raise ActionError(f"action {action_id} was already undone", 409)
    if entry.inverse is None:
        raise ActionError(f"action {action_id} ({entry.action_type}) cannot be undone", 409)

    with ctx.session.begin_nested():
        for step in entry.inverse:
            defn = REGISTRY[step["action_type"]]
            _run(ctx, defn, _parse(defn, step["payload"]))
        entry.undone_at = ctx.now
    ctx.session.flush()
    return entry
