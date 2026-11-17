from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.actions.base import ActionError
from app.config import FALLBACK_CATEGORY, JOBS
from app.models import Base, Category


def resolve_category(
    session: Session, category: str | None, category_id: int | None
) -> Category:
    """By id, else by name (case-insensitive), else the fallback category."""
    if category_id is not None:
        found = session.get(Category, category_id)
        if found is None:
            raise ActionError(f"category {category_id} not found", 404)
        return found
    name = category or FALLBACK_CATEGORY
    found = session.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if found is None:
        raise ActionError(f"unknown category {name!r}")
    return found


def check_job(category: Category, job: str | None) -> None:
    if job is not None and job not in JOBS:
        raise ActionError(f"unknown job {job!r}; expected one of {sorted(JOBS)}")
    if category.is_work and job is None:
        raise ActionError(f"{category.name} is a work category; a job is required")


def get_or_404[T: Base](session: Session, model: type[T], row_id: int, *, lock=False) -> T:
    row = session.get(model, row_id, with_for_update=lock)
    if row is None:
        raise ActionError(f"{model.__tablename__} {row_id} not found", 404)
    return row


def set_fields(row: Base, values: dict[str, Any], snapshot: type[BaseModel]) -> dict[str, Any]:
    """Assign attributes and return the previous values, JSON-encoded via the
    row's snapshot model so they can be stored as an inverse payload."""
    before = snapshot.model_validate(row).model_dump(mode="json", include=set(values))
    for key, value in values.items():
        setattr(row, key, value)
    return before
