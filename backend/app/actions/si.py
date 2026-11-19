"""SI weekly plan: update_si_session upserts one week's row.

Undo: a first save (row created) is undone by deleting the row, which makes the
week read as defaults again; a later save restores the previous values.
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import get_or_404, set_fields
from app.models import SiSession
from app.schemas import SiSessionOut
from app.timeutil import AwareDatetime

CHECKLIST = ("plan_form_done", "slides_done", "breakdown_done", "answer_sheet_done")
_LABELS = {
    "topic": "topic", "plan_form_done": "plan form", "slides_done": "slides",
    "breakdown_done": "90-min breakdown", "answer_sheet_done": "answer sheet",
    "session_at": "session time", "attendance": "attendance",
}


def check_monday(week_of: date) -> date:
    if week_of.weekday() != 0:
        raise ValueError(f"week_of must be a Monday; {week_of} is a {week_of:%A}")
    return week_of


class SiSessionPatch(BaseModel):
    """Any subset; explicit null clears topic, session_at or attendance."""

    topic: str | None = Field(default=None, max_length=300)
    plan_form_done: bool | None = None
    slides_done: bool | None = None
    breakdown_done: bool | None = None
    answer_sheet_done: bool | None = None
    session_at: AwareDatetime | None = None
    attendance: int | None = Field(default=None, ge=0)


class UpdateSiSession(BaseModel):
    week_of: date
    fields: SiSessionPatch

    _monday = field_validator("week_of")(check_monday)


class SiFieldValues(BaseModel):
    topic: str | None = None
    plan_form_done: bool | None = None
    slides_done: bool | None = None
    breakdown_done: bool | None = None
    answer_sheet_done: bool | None = None
    session_at: AwareDatetime | None = None
    attendance: int | None = None


class RestoreSiFields(BaseModel):
    si_session_id: int
    values: SiFieldValues


class SiRef(BaseModel):
    si_session_id: int


class RestoreSi(BaseModel):
    si_session: SiSessionOut


def _result(row: SiSession) -> dict:
    return {"si_session": SiSessionOut.model_validate(row).model_dump(mode="json")}


def _describe(week_of: date, patch: dict) -> str:
    parts = []
    for key, value in patch.items():
        label = _LABELS[key]
        if key in CHECKLIST:
            parts.append(f"{label} {'done' if value else 'not done'}")
        elif value is None:
            parts.append(f"{label} cleared")
        elif key == "topic":
            parts.append(f'topic "{value}"')
        else:
            parts.append(f"{label} set")
    return f"SI week of {week_of:%b} {week_of.day}: " + ", ".join(parts)


@action("update_si_session", UpdateSiSession)
def update_si_session(ctx: ActionContext, p: UpdateSiSession) -> Outcome:
    patch = p.fields.model_dump(exclude_unset=True)
    if not patch:
        raise ActionError("update_si_session needs at least one field")
    for key in CHECKLIST:
        if key in patch and patch[key] is None:
            raise ActionError(f"{key} must be true or false")
    if isinstance(patch.get("topic"), str):
        patch["topic"] = patch["topic"].strip() or None

    row = ctx.session.scalar(
        select(SiSession).where(SiSession.week_of == p.week_of).with_for_update()
    )
    if row is None:
        row = SiSession(week_of=p.week_of, **patch)
        ctx.session.add(row)
        ctx.session.flush()
        inverse = [Step("delete_si_session", {"si_session_id": row.id})]
    else:
        before = set_fields(row, patch, SiSessionOut)
        ctx.session.flush()
        inverse = [Step("restore_si_session_fields", {"si_session_id": row.id, "values": before})]
    return Outcome(_describe(p.week_of, patch), inverse, _result(row))


@action("restore_si_session_fields", RestoreSiFields, internal=True)
def restore_si_session_fields(ctx: ActionContext, p: RestoreSiFields) -> Outcome:
    row = get_or_404(ctx.session, SiSession, p.si_session_id, lock=True)
    before = set_fields(row, p.values.model_dump(exclude_unset=True), SiSessionOut)
    return Outcome(
        f"Restored SI week of {row.week_of}",
        [Step("restore_si_session_fields", {"si_session_id": row.id, "values": before})],
    )


@action("delete_si_session", SiRef, internal=True)
def delete_si_session(ctx: ActionContext, p: SiRef) -> Outcome:
    row = get_or_404(ctx.session, SiSession, p.si_session_id, lock=True)
    snapshot = SiSessionOut.model_validate(row).model_dump(mode="json")
    ctx.session.delete(row)
    ctx.session.flush()
    return Outcome(f"Cleared SI week of {snapshot['week_of']}",
                   [Step("restore_si_session", {"si_session": snapshot})])


@action("restore_si_session", RestoreSi, internal=True)
def restore_si_session(ctx: ActionContext, p: RestoreSi) -> Outcome:
    data = p.si_session.model_dump()
    if ctx.session.get(SiSession, data["id"]) is not None:
        raise ActionError(f"SI session {data['id']} already exists", 409)
    if ctx.session.scalar(select(SiSession.id).where(SiSession.week_of == data["week_of"])):
        raise ActionError(f"SI week of {data['week_of']} already has a row", 409)
    row = SiSession(**data)
    ctx.session.add(row)
    ctx.session.flush()
    return Outcome(f"Restored SI week of {row.week_of}",
                   [Step("delete_si_session", {"si_session_id": row.id})])
