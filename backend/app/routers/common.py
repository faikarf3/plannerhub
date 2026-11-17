from typing import Any

from pydantic import BaseModel

from app.actions import ActionContext, apply_action
from app.schemas import ActionOut


def run(ctx: ActionContext, action_type: str, payload: BaseModel | dict[str, Any]) -> ActionOut:
    applied = apply_action(ctx, action_type, payload)
    return ActionOut(
        action_id=applied.action_id,
        action_type=applied.action_type,
        summary=applied.summary,
        result=applied.result,
    )
