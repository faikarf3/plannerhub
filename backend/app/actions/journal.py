"""Raw input storage and the /log pipeline (quick-add first, then the AI extractor).

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
from app.extract import (
    SYSTEM_PROMPT,
    TOOLS,
    Extraction,
    ExtractionError,
    Extractor,
    build_prompt,
    find_invented_time,
    invented_time_question,
)
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
    via: Literal["quickadd", "ai"] | None = None
    clarify: dict | None = None  # {"question", "options"}: asked instead of applying


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


def handle_log(
    ctx: ActionContext, text: str, at: datetime | None = None,
    extractor: Extractor | None = None,
) -> LogResult:
    """Typed input: journal it, quick-add parse it, apply what was understood.
    Text the parser can't read goes to the extractor (when configured)."""
    journal = record_journal_entry(ctx, text, "typed", at)
    names = list(ctx.session.scalars(select(Category.name)))
    intents = parse(text, at or ctx.now, names)
    if intents is None:
        if extractor is None:
            return LogResult(journal.id, parsed=False)
        return _extract_and_apply(ctx, journal, extractor)

    result = LogResult(journal.id, parsed=True, via="quickadd")
    try:
        for intent in intents:
            result.actions.append(_apply_intent(ctx, intent, at, journal.id))
    except ActionError as e:
        result.error = e.message
    return result


def handle_clarify(
    ctx: ActionContext, journal_id: int, answer: str, extractor: Extractor | None
) -> LogResult:
    """Answer the question a journal entry is waiting on, then re-run extraction
    on the original text plus the answer."""
    journal = ctx.session.get(JournalEntry, journal_id, with_for_update=True)
    if journal is None:
        raise ActionError(f"journal entry {journal_id} not found", 404)
    if journal.clarify_question is None or journal.clarify_answer is not None:
        raise ActionError(f"journal entry {journal_id} has no open question", 409)
    if extractor is None:
        raise ActionError("AI extraction is not configured on this server", 503)
    question = journal.clarify_question["question"]
    journal.clarify_answer = answer
    return _extract_and_apply(ctx, journal, extractor, (question, answer))


def _extract_and_apply(
    ctx: ActionContext, journal: JournalEntry, extractor: Extractor,
    followup: tuple[str, str] | None = None,
) -> LogResult:
    # The journal's timestamp is when it was said (offline queue), so relative
    # times resolve against that, not upload or answer time.
    said_at = journal.created_at
    prompt = build_prompt(ctx.session, said_at, journal.raw_text, followup)
    try:
        extraction = extractor.extract(SYSTEM_PROMPT, prompt, TOOLS)
    except ExtractionError as e:
        return LogResult(journal.id, parsed=False, error=f"AI unavailable: {e}")

    # Everything the user has said so far backs times: the log plus any answer.
    said = journal.raw_text + (f" {followup[1]}" if followup else "")
    for call in extraction.calls:
        if field_name := find_invented_time(call, said, said_at):
            extraction = Extraction(clarify=invented_time_question(call, field_name))
            break

    if extraction.clarify:
        q = extraction.clarify
        journal.clarify_question = {"question": q.question, "options": q.options}
        journal.clarify_answer = None
        ctx.session.flush()
        return LogResult(journal.id, parsed=True, via="ai", clarify=journal.clarify_question)
    if not extraction.calls:
        return LogResult(journal.id, parsed=False, via="ai")

    result = LogResult(journal.id, parsed=True, via="ai")
    try:
        for call in extraction.calls:
            args = dict(call.args)
            if call.name in _TIMED and "at" not in args:
                args["at"] = said_at
            if call.name == "set_mood":
                args["journal_entry_id"] = journal.id  # mood belongs to what was said
            result.actions.append(
                apply_action(ctx, call.name, args, journal_entry_id=journal.id)
            )
    except ActionError as e:
        result.error = e.message
    return result
