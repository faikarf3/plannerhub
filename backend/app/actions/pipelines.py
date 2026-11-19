"""Actions behind pipeline events: per-pipeline keys, job applications and
3AM Facts nights. Events call these through apply_action like any other input."""

import hashlib
import secrets
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import get_or_404, set_fields
from app.config import PIPELINES
from app.models import Application, ContentItem, PipelineKey
from app.schemas import ApplicationOut, ContentItemOut, PipelineKeyOut
from app.timeutil import AwareDatetime

ApplicationStatus = Literal["applied", "oa", "interview", "offer", "rejected", "ghosted"]
ContentStatus = Literal["created", "posted", "failed", "missing"]


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------- keys


class CreatePipelineKey(BaseModel):
    source: str


class KeyRef(BaseModel):
    key_id: int


@action("create_pipeline_key", CreatePipelineKey)
def create_pipeline_key(ctx: ActionContext, p: CreatePipelineKey) -> Outcome:
    if p.source not in PIPELINES:
        raise ActionError(f"unknown pipeline {p.source!r}; expected one of {sorted(PIPELINES)}")
    key = "ph_" + secrets.token_urlsafe(32)
    row = PipelineKey(source=p.source, key_hash=hash_key(key), hint=key[:10])
    ctx.session.add(row)
    ctx.session.flush()
    # The key itself is only in this response; action_log keeps just the source.
    return Outcome(
        f"Created a key for {p.source} ({row.hint}…)",
        [Step("revoke_pipeline_key", {"key_id": row.id})],
        {"key": key, "pipeline_key": PipelineKeyOut.model_validate(row).model_dump(mode="json")},
    )


@action("revoke_pipeline_key", KeyRef)
def revoke_pipeline_key(ctx: ActionContext, p: KeyRef) -> Outcome:
    row = get_or_404(ctx.session, PipelineKey, p.key_id, lock=True)
    if row.revoked_at is not None:
        raise ActionError(f"key {row.id} is already revoked", 409)
    row.revoked_at = ctx.now
    return Outcome(f"Revoked {row.source} key {row.hint}…",
                   [Step("unrevoke_pipeline_key", {"key_id": row.id})])


@action("unrevoke_pipeline_key", KeyRef, internal=True)
def unrevoke_pipeline_key(ctx: ActionContext, p: KeyRef) -> Outcome:
    row = get_or_404(ctx.session, PipelineKey, p.key_id, lock=True)
    row.revoked_at = None
    return Outcome(f"Restored {row.source} key {row.hint}…",
                   [Step("revoke_pipeline_key", {"key_id": row.id})])


# ---------------------------------------------------------------- applications


class SaveApplication(BaseModel):
    """New application, or an update to the one it matches: same company and role
    (case-insensitive); with no role given, the company's most recent one."""

    company: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    url: str | None = None
    status: ApplicationStatus | None = None
    applied_at: AwareDatetime | None = None
    replied_at: AwareDatetime | None = None


class ApplicationRef(BaseModel):
    application_id: int


class ApplicationFieldValues(BaseModel):
    role: str | None = None
    url: str | None = None
    status: ApplicationStatus | None = None
    applied_at: AwareDatetime | None = None
    replied_at: AwareDatetime | None = None


class RestoreApplicationFields(BaseModel):
    application_id: int
    values: ApplicationFieldValues


def _match_application(ctx: ActionContext, company: str, role: str | None) -> Application | None:
    rows = list(ctx.session.scalars(
        select(Application).where(func.lower(Application.company) == company.lower())
        .order_by(Application.id.desc()).with_for_update()
    ))
    if role is None:
        return rows[0] if rows else None
    exact = [a for a in rows if a.role and a.role.lower() == role.lower()]
    return (exact or [a for a in rows if a.role is None] or [None])[0]


def _application_result(app: Application) -> dict:
    return {"application": ApplicationOut.model_validate(app).model_dump(mode="json")}


def _label(app: Application) -> str:
    return f"{app.company} ({app.role})" if app.role else app.company


@action("save_application", SaveApplication)
def save_application(ctx: ActionContext, p: SaveApplication) -> Outcome:
    app = _match_application(ctx, p.company, p.role)
    values = p.model_dump(exclude={"company"}, exclude_none=True)
    if app is None:
        app = Application(company=p.company.strip(), **{"status": "applied", **values})
        ctx.session.add(app)
        ctx.session.flush()
        verb = "Applied" if app.status == "applied" else f"New application, {app.status}"
        return Outcome(f"{verb}: {_label(app)}",
                       [Step("delete_application", {"application_id": app.id})],
                       _application_result(app))
    if not values:
        raise ActionError(f"nothing to update on {_label(app)}")
    before = set_fields(app, values, ApplicationOut)
    ctx.session.flush()
    what = f"now {app.status}" if "status" in values else ", ".join(values)
    return Outcome(f"{_label(app)}: {what}",
                   [Step("restore_application_fields",
                         {"application_id": app.id, "values": before})],
                   _application_result(app))


@action("delete_application", ApplicationRef, internal=True)
def delete_application(ctx: ActionContext, p: ApplicationRef) -> Outcome:
    app = get_or_404(ctx.session, Application, p.application_id, lock=True)
    label = _label(app)
    ctx.session.delete(app)
    ctx.session.flush()
    return Outcome(f"Removed application {label}", None)  # only ever an inverse


@action("restore_application_fields", RestoreApplicationFields, internal=True)
def restore_application_fields(ctx: ActionContext, p: RestoreApplicationFields) -> Outcome:
    app = get_or_404(ctx.session, Application, p.application_id, lock=True)
    before = set_fields(app, p.values.model_dump(exclude_unset=True), ApplicationOut)
    return Outcome(f"Restored {_label(app)}",
                   [Step("restore_application_fields",
                         {"application_id": app.id, "values": before})])


# ---------------------------------------------------------------- 3AM Facts nights


class SaveContentItem(BaseModel):
    """Create or update the night's row. A posted night is never downgraded to
    created; `platform` + `post_url` add one entry to `posts`."""

    run_date: date
    status: ContentStatus | None = None
    title: str | None = None
    url: str | None = None
    platform: str | None = Field(default=None, max_length=40)
    post_url: str | None = None
    error: str | None = None


class ContentRef(BaseModel):
    content_id: int


class ContentFieldValues(BaseModel):
    title: str | None = None
    url: str | None = None
    status: ContentStatus | None = None
    posts: dict | None = None
    error: str | None = None


class RestoreContentFields(BaseModel):
    content_id: int
    values: ContentFieldValues


_RANK = {"missing": 0, "failed": 1, "created": 2, "posted": 3}


def _content_result(item: ContentItem) -> dict:
    return {"content_item": ContentItemOut.model_validate(item).model_dump(mode="json")}


@action("save_content_item", SaveContentItem)
def save_content_item(ctx: ActionContext, p: SaveContentItem) -> Outcome:
    item = ctx.session.scalar(
        select(ContentItem).where(ContentItem.run_date == p.run_date).with_for_update()
    )
    values = p.model_dump(include={"title", "url", "error"}, exclude_none=True)
    if p.status is not None:
        current = item.status if item else None
        # A late "created" after "posted" (events out of order) keeps "posted".
        if current is None or p.status in ("failed", "missing") or _RANK[p.status] > _RANK[current]:
            values["status"] = p.status
    if p.platform:
        posts = dict(item.posts) if item else {}
        posts[p.platform.lower()] = p.post_url
        values["posts"] = posts

    night = p.run_date.strftime("%a %b %-d")
    if item is None:
        item = ContentItem(run_date=p.run_date, **{"status": "created", "posts": {}, **values})
        ctx.session.add(item)
        ctx.session.flush()
        return Outcome(f"3AM Facts {night}: {item.status}",
                       [Step("delete_content_item", {"content_id": item.id})],
                       _content_result(item))
    if not values:
        return Outcome(f"3AM Facts {night}: no change", [], _content_result(item))
    before = set_fields(item, values, ContentItemOut)
    ctx.session.flush()
    return Outcome(f"3AM Facts {night}: {item.status}",
                   [Step("restore_content_fields", {"content_id": item.id, "values": before})],
                   _content_result(item))


@action("delete_content_item", ContentRef, internal=True)
def delete_content_item(ctx: ActionContext, p: ContentRef) -> Outcome:
    item = get_or_404(ctx.session, ContentItem, p.content_id, lock=True)
    ctx.session.delete(item)
    ctx.session.flush()
    return Outcome("Removed 3AM Facts night", None)  # only ever an inverse


@action("restore_content_fields", RestoreContentFields, internal=True)
def restore_content_fields(ctx: ActionContext, p: RestoreContentFields) -> Outcome:
    item = get_or_404(ctx.session, ContentItem, p.content_id, lock=True)
    before = set_fields(item, p.values.model_dump(exclude_unset=True), ContentItemOut)
    return Outcome("Restored 3AM Facts night",
                   [Step("restore_content_fields", {"content_id": item.id, "values": before})])
