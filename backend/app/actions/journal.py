"""Raw input storage and the /log pipeline.

Journal entries are the raw record of what was said or typed. They're written
here (not as a registered action) because they aren't planner changes and
aren't undoable; every planner change they lead to goes through apply_action
with journal_entry_id set.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from app.actions.base import ActionContext, ActionError, AppliedAction, apply_action
from app.models import Category, JournalEntry, Task
from app.quickadd import Intent, parse

# Actions whose timing should follow the moment of input (offline queue).
_TIMED = {"start_timer", "stop_timer"}


def record_journal_entry(
    ctx: ActionContext, text: str, input_type: Literal["voice", "typed"],
    at: datetime | None = None, audio_url: str | None = None,
) -> JournalEntry:
    entry = JournalEntry(
        input_type=input_type, raw_text=text, audio_url=audio_url, created_at=at or ctx.now
    )
    ctx.session.add(entry)
    ctx.session.flush()
    return entry


@dataclass
class LogResult:
    journal_entry_id: int
    parsed: bool
    actions: list[AppliedAction] = field(default_factory=list)
    error: str | None = None


def _find_open_task(ctx: ActionContext, query: str) -> Task:
    words = query.lower().split()
    q = select(Task).where(Task.status.in_(("todo", "doing")))
    for w in words:
        w = w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.where(Task.title.ilike(f"%{w}%", escape="\\"))
    matches = list(ctx.session.scalars(q.limit(6)))
    if not matches:
        raise ActionError(f'no open task matches "{query}"', 404)
    if len(matches) > 1:
        titles = ", ".join(f'"{t.title}"' for t in matches[:5])
        raise ActionError(f'"{query}" matches several tasks: {titles}', 409)
    return matches[0]


def _apply_intent(
    ctx: ActionContext, intent: Intent, at: datetime | None, journal_id: int
) -> AppliedAction:
    kind, payload = intent.kind, dict(intent.payload)
    if kind == "complete_task_by_title":
        task = _find_open_task(ctx, payload["query"])
        kind, payload = "complete_task", {"task_id": task.id}
        if at:
            payload["completed_at"] = at
    elif kind in _TIMED and at and "at" not in payload:
        payload["at"] = at
    return apply_action(ctx, kind, payload, journal_entry_id=journal_id)


def handle_log(ctx: ActionContext, text: str, at: datetime | None = None) -> LogResult:
    """Typed input: journal it, quick-add parse it, apply what was understood.
    Unparsed text is kept in the journal (Phase 2 sends it to Claude)."""
    journal = record_journal_entry(ctx, text, "typed", at)
    names = list(ctx.session.scalars(select(Category.name)))
    intents = parse(text, at or ctx.now, names)
    if intents is None:
        return LogResult(journal.id, parsed=False)

    result = LogResult(journal.id, parsed=True)
    try:
        for intent in intents:
            result.actions.append(_apply_intent(ctx, intent, at, journal.id))
    except ActionError as e:
        result.error = e.message
    return result
