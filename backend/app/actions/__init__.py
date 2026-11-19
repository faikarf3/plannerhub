"""Importing this package registers every action in REGISTRY."""

from app.actions import (  # noqa: F401
    categories,
    climbs,
    mood,
    pipelines,
    schedules,
    si,
    tasks,
    time_entries,
)
from app.actions.base import (
    REGISTRY,
    ActionContext,
    ActionError,
    AppliedAction,
    apply_action,
    undo_action,
)

__all__ = [
    "REGISTRY",
    "ActionContext",
    "ActionError",
    "AppliedAction",
    "apply_action",
    "undo_action",
]
