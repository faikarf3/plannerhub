from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.actions.journal import handle_log
from app.deps import CtxDep
from app.schemas import ActionOut
from app.timeutil import AwareDatetime

router = APIRouter(tags=["log"])


class LogBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # When it was typed (offline queue); defaults to now. Times like "at 5pm" in
    # the text still win.
    at: AwareDatetime | None = None


class LogOut(BaseModel):
    """Same shape /voice will return. `parsed=false` means the quick-add parser
    didn't understand the text; it's saved in the journal either way."""

    journal_entry_id: int
    parsed: bool
    actions: list[ActionOut]
    error: str | None
    message: str


@router.post("/log")
def log(body: LogBody, ctx: CtxDep) -> LogOut:
    result = handle_log(ctx, body.text, body.at)
    actions = [ActionOut(**vars(a)) for a in result.actions]
    if result.error:
        message = result.error
    elif not result.parsed:
        message = "Didn't catch that; saved to your journal."
    else:
        message = "\n".join(a.summary for a in actions)
    return LogOut(
        journal_entry_id=result.journal_entry_id, parsed=result.parsed,
        actions=actions, error=result.error, message=message,
    )
