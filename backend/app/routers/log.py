from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.actions.journal import LogResult, handle_clarify, handle_log
from app.deps import CtxDep
from app.extract import Extractor, get_extractor
from app.schemas import ActionOut
from app.timeutil import AwareDatetime

router = APIRouter(tags=["log"])

ExtractorDep = Annotated[Extractor | None, Depends(get_extractor)]


class LogBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # When it was typed (offline queue); defaults to now. Times like "at 5pm" in
    # the text still win.
    at: AwareDatetime | None = None


class ClarifyBody(BaseModel):
    answer: str = Field(min_length=1, max_length=500)


class ClarifyOut(BaseModel):
    question: str
    options: list[str]


class LogOut(BaseModel):
    """Same shape /voice will return. `parsed=false` means nothing actionable was
    understood; the text is saved in the journal either way. `via` says whether
    the quick-add parser or the AI handled it. When `clarify` is set nothing was
    applied: answer it with POST /clarify/{journal_entry_id}."""

    journal_entry_id: int
    parsed: bool
    via: Literal["quickadd", "ai"] | None
    actions: list[ActionOut]
    clarify: ClarifyOut | None
    error: str | None
    message: str


def _out(result: LogResult) -> LogOut:
    actions = [ActionOut(**vars(a)) for a in result.actions]
    if result.error and not actions:
        message = result.error
    elif result.error:
        message = "\n".join(a.summary for a in actions) + f"\nStopped: {result.error}"
    elif result.clarify:
        message = result.clarify["question"]
    elif not result.parsed:
        message = "Didn't catch anything to log; saved to your journal."
    else:
        message = "\n".join(a.summary for a in actions)
    return LogOut(
        journal_entry_id=result.journal_entry_id, parsed=result.parsed, via=result.via,
        actions=actions, clarify=ClarifyOut(**result.clarify) if result.clarify else None,
        error=result.error, message=message,
    )


@router.post("/log")
def log(body: LogBody, ctx: CtxDep, extractor: ExtractorDep) -> LogOut:
    return _out(handle_log(ctx, body.text, body.at, extractor))


@router.post("/clarify/{journal_id}")
def clarify(journal_id: int, body: ClarifyBody, ctx: CtxDep, extractor: ExtractorDep) -> LogOut:
    return _out(handle_clarify(ctx, journal_id, body.answer, extractor))
