"""Mood and energy, stored on the journal entry they were said in."""

from pydantic import BaseModel, Field

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import get_or_404
from app.models import JournalEntry


class SetMood(BaseModel):
    journal_entry_id: int
    # Only fields that were sent are changed; an explicit null clears one
    # (that's how undo restores "not set").
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)


@action("set_mood", SetMood)
def set_mood(ctx: ActionContext, p: SetMood) -> Outcome:
    values = p.model_dump(include={"mood", "energy"}, exclude_unset=True)
    if not values:
        raise ActionError("set_mood needs mood or energy")
    entry = get_or_404(ctx.session, JournalEntry, p.journal_entry_id, lock=True)
    before = {key: getattr(entry, key) for key in values}
    for key, value in values.items():
        setattr(entry, key, value)

    parts = [f"{key} {value}/5" for key, value in values.items() if value is not None]
    summary = ("Noted " + ", ".join(parts)) if parts else "Cleared mood/energy"
    inverse = [Step("set_mood", {"journal_entry_id": entry.id, **before})]
    return Outcome(summary, inverse, {"journal_entry_id": entry.id, **values})
