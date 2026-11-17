from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="PLANNER_", extra="ignore")

    database_url: str = "postgresql+psycopg:///planner_hub"
    # Single-user bearer token until the Flutter app moves auth to Firebase.
    api_token: str


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
MIN_ENTRY_MINUTES = 2
LONG_TIMER_HOURS = 4
