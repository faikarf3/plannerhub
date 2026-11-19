from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _sqlalchemy_url(url: str) -> str:
    """Accept plain Postgres URLs (as Neon and most hosts give them) and point
    SQLAlchemy at the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    # Repo-root .env.local (written by `neon init`), then backend/.env; real env vars win.
    # PLANNER_DATABASE_URL in backend/.env keeps local dev on the local database even
    # though .env.local holds Neon's DATABASE_URL. Deployed, only DATABASE_URL is set.
    model_config = SettingsConfigDict(
        env_file=("../.env.local", ".env"), env_prefix="PLANNER_", extra="ignore"
    )

    database_url: str = Field(
        default="postgresql+psycopg:///planner_hub",
        validation_alias=AliasChoices("PLANNER_DATABASE_URL", "DATABASE_URL"),
    )
    # Direct (non-pooled) connection for migrations; falls back to database_url.
    # Deliberately not read from Neon's DATABASE_URL_UNPOOLED automatically, so a local
    # `alembic upgrade` can never hit Neon by accident -- use scripts/with-neon.sh.
    migration_database_url: str | None = None
    # Single-user bearer token until the Flutter app moves auth to Firebase.
    api_token: str
    # Fallback extraction for text the quick-add parser can't read. Unset or empty
    # turns it off: unparsed text is then only saved to the journal.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _driver(cls, v: str | None) -> str | None:
        return _sqlalchemy_url(v) if v else v


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Work jobs and the category a clock-in for each lands in by default.
# Categories are data; this map only supplies defaults for the clock-in shortcut.
JOBS: dict[str, str] = {
    "tutoring": "Work",
    "si_session": "Work",
    "si_prep": "SI Prep",
    "restaurant": "Work",
}

JOB_LABELS: dict[str, str] = {
    "tutoring": "Tutoring",
    "si_session": "SI session",
    "si_prep": "SI prep",
    "restaurant": "Restaurant",
}

# Quick-add vocabulary: word(s) -> (category name, job). Category names themselves
# also match automatically, so a new category is usable in quick-add without code.
ACTIVITIES: dict[str, tuple[str, str | None]] = {
    **{w: ("Climbing", None) for w in ("climb", "climbing", "climbed", "bouldering")},
    **{w: ("Work", "tutoring") for w in ("tutoring", "tutor", "tutored")},
    **{w: ("Work", "si_session") for w in ("si", "si session", "si sessions")},
    **{w: ("SI Prep", "si_prep") for w in ("si prep", "prep")},
    **{w: ("Work", "restaurant") for w in ("restaurant", "restaurant shift")},
    **{w: ("Job Search", None)
       for w in ("job search", "applications", "applying", "apps", "jobs")},
    **{w: ("3AM Facts", None) for w in ("3am facts", "3am")},
    **{w: ("School", None) for w in ("school", "study", "studying", "class", "homework")},
    **{w: ("Personal", None) for w in ("rest", "commute", "errands", "social")},
}

FALLBACK_CATEGORY = "Personal"
# log_climb files its time entry here; GET /climbs lists this category's entries.
CLIMBING_CATEGORY = "Climbing"
# Pipelines that may post to /events, and the event types each one sends.
PIPELINES: dict[str, frozenset[str]] = {
    "3am_facts": frozenset({"video_created", "posted", "run_failed"}),
    "job_tracker": frozenset(
        {"application_submitted", "reply_received", "run_finished", "run_failed"}
    ),
}
FACTS_CATEGORY = "3AM Facts"
JOB_SEARCH_CATEGORY = "Job Search"
# Local hour by which last night's 3AM Facts video should have reported; after it,
# POST /pipelines/check marks the night missing.
FACTS_REPORT_BY_HOUR = 7
DAILY_APPLICATION_TARGET = 20

MIN_ENTRY_MINUTES = 2
LONG_TIMER_HOURS = 4
