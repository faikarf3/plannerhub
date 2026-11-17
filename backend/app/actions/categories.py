from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.actions.base import ActionContext, ActionError, Outcome, Step, action
from app.actions.common import get_or_404, resolve_category
from app.models import Category, Task, TimeEntry
from app.schemas import CategoryOut


class CreateCategory(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = None
    parent: str | None = None
    is_work: bool = False
    weekly_target_hours: Decimal | None = Field(default=None, ge=0)


class CategoryRef(BaseModel):
    category_id: int


@action("create_category", CreateCategory)
def create_category(ctx: ActionContext, p: CreateCategory) -> Outcome:
    taken = ctx.session.scalar(
        select(Category.id).where(func.lower(Category.name) == p.name.lower())
    )
    if taken is not None:
        raise ActionError(f"category {p.name!r} already exists", 409)
    parent_id = resolve_category(ctx.session, p.parent, None).id if p.parent else None
    category = Category(
        name=p.name, color=p.color, parent_id=parent_id, is_work=p.is_work,
        weekly_target_hours=p.weekly_target_hours,
    )
    ctx.session.add(category)
    ctx.session.flush()
    return Outcome(
        f"Added category {category.name}",
        [Step("delete_category", {"category_id": category.id})],
        {"category": CategoryOut.model_validate(category).model_dump(mode="json")},
    )


@action("delete_category", CategoryRef, internal=True)
def delete_category(ctx: ActionContext, p: CategoryRef) -> Outcome:
    category = get_or_404(ctx.session, Category, p.category_id, lock=True)
    for model in (Task, TimeEntry):
        if ctx.session.scalar(select(model.id).where(model.category_id == category.id).limit(1)):
            raise ActionError(f"category {category.name} is in use", 409)
    if ctx.session.scalar(select(Category.id).where(Category.parent_id == category.id).limit(1)):
        raise ActionError(f"category {category.name} has sub-categories", 409)
    ctx.session.delete(category)
    return Outcome(f"Deleted category {category.name}", None)
