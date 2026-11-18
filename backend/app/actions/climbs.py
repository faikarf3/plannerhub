"""Climbing sessions: a time entry in the climbing category plus a `climbs` row
holding the gym and notes."""

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import get_or_404, resolve_category, set_fields
from app.actions.time_entries import LogTime, TimeSource, log_time
from app.config import CLIMBING_CATEGORY
from app.models import Climb, TimeEntry
from app.schemas import ClimbOut, TimeEntryOut
from app.timeutil import AwareDatetime

_TIME_FIELDS = ("started_at", "ended_at", "duration_min")


class LogClimb(BaseModel):
    """A new session (times as in log_time), or details for an existing climbing
    entry via time_entry_id (e.g. a stopped timer). Gym/notes left out stay as they are."""

    time_entry_id: int | None = None
    gym: str | None = Field(default=None, max_length=100)
    notes: str | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    duration_min: int | None = Field(default=None, gt=0)
    confirmed: bool = True
    source: TimeSource = "manual"


class ClimbRef(BaseModel):
    climb_id: int


class ClimbFieldValues(BaseModel):
    gym: str | None = None
    notes: str | None = None


class RestoreClimbFields(BaseModel):
    climb_id: int
    values: ClimbFieldValues


class RestoreClimb(BaseModel):
    climb: ClimbOut


def _result(climb: Climb, entry: TimeEntry) -> dict:
    return {
        "climb": ClimbOut.model_validate(climb).model_dump(mode="json"),
        "time_entry": TimeEntryOut.model_validate(entry).model_dump(mode="json"),
    }


def _known_gym(ctx: ActionContext, gym: str | None) -> str | None:
    """Reuse the spelling of a gym already logged ("vital" -> "Vital")."""
    if gym is None or not gym.strip():
        return None
    gym = gym.strip()
    existing = ctx.session.scalar(
        select(Climb.gym).where(func.lower(Climb.gym) == gym.lower())
        .order_by(Climb.id.desc()).limit(1)
    )
    if existing:
        return existing
    return gym.title() if gym.islower() else gym  # dictation/typing often skips capitals


def _details(p: LogClimb, ctx: ActionContext) -> dict:
    values = p.model_dump(include={"gym", "notes"}, exclude_unset=True)
    if "gym" in values:
        values["gym"] = _known_gym(ctx, values["gym"])
    return values


def _at_gym(climb: Climb) -> str:
    return f" at {climb.gym}" if climb.gym else ""


@action("log_climb", LogClimb)
def log_climb(ctx: ActionContext, p: LogClimb) -> Outcome:
    climbing = resolve_category(ctx.session, CLIMBING_CATEGORY, None)
    details = _details(p, ctx)

    if p.time_entry_id is None:
        logged = log_time(ctx, LogTime(
            category_id=climbing.id, confirmed=p.confirmed, source=p.source,
            **p.model_dump(include=set(_TIME_FIELDS), exclude_unset=True),
        ))
        entry_id = logged.result["time_entry"]["id"]
        climb = Climb(time_entry_id=entry_id, **details)
        ctx.session.add(climb)
        ctx.session.flush()
        entry = ctx.session.get(TimeEntry, entry_id)
        # Deleting the entry cascades to the climb.
        return Outcome(logged.summary + _at_gym(climb), logged.inverse, _result(climb, entry))

    if p.model_fields_set & set(_TIME_FIELDS):
        raise ActionError("give time_entry_id or times, not both; "
                          "change times with update_time_entry")
    entry = get_or_404(ctx.session, TimeEntry, p.time_entry_id)
    if entry.category_id != climbing.id:
        raise ActionError(f"time entry {entry.id} is not {CLIMBING_CATEGORY}")
    climb = ctx.session.scalar(
        select(Climb).where(Climb.time_entry_id == entry.id).with_for_update()
    )
    if climb is None:
        climb = Climb(time_entry_id=entry.id, **details)
        ctx.session.add(climb)
        ctx.session.flush()
        inverse = [Step("delete_climb", {"climb_id": climb.id})]
    else:
        if not details:
            raise ActionError("log_climb on an existing climb needs gym or notes")
        before = set_fields(climb, details, ClimbOut)
        ctx.session.flush()
        inverse = [Step("restore_climb_fields", {"climb_id": climb.id, "values": before})]
    return Outcome(f"Saved climb details{_at_gym(climb)}", inverse, _result(climb, entry))


@action("delete_climb", ClimbRef, internal=True)
def delete_climb(ctx: ActionContext, p: ClimbRef) -> Outcome:
    climb = get_or_404(ctx.session, Climb, p.climb_id, lock=True)
    snapshot = ClimbOut.model_validate(climb).model_dump(mode="json")
    ctx.session.delete(climb)
    ctx.session.flush()
    return Outcome("Removed climb details", [Step("restore_climb", {"climb": snapshot})])


@action("restore_climb", RestoreClimb, internal=True)
def restore_climb(ctx: ActionContext, p: RestoreClimb) -> Outcome:
    if ctx.session.get(Climb, p.climb.id) is not None:
        raise ActionError(f"climb {p.climb.id} already exists", 409)
    get_or_404(ctx.session, TimeEntry, p.climb.time_entry_id)
    climb = Climb(**p.climb.model_dump())
    ctx.session.add(climb)
    ctx.session.flush()
    return Outcome("Restored climb details", [Step("delete_climb", {"climb_id": climb.id})])


@action("restore_climb_fields", RestoreClimbFields, internal=True)
def restore_climb_fields(ctx: ActionContext, p: RestoreClimbFields) -> Outcome:
    climb = get_or_404(ctx.session, Climb, p.climb_id, lock=True)
    values = p.values.model_dump(exclude_unset=True)
    before = set_fields(climb, values, ClimbOut)
    ctx.session.flush()
    return Outcome("Restored climb details",
                   [Step("restore_climb_fields", {"climb_id": climb.id, "values": before})])
