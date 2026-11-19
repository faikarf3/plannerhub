"""Importing this package registers every action in REGISTRY."""

from app.actions import categories, climbs, mood, pipelines, tasks, time_entries  # noqa: F401
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
