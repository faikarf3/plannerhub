from app.config import Settings


def test_neon_style_url_gets_psycopg_driver(monkeypatch):
    monkeypatch.delenv("PLANNER_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-x.us-east-1.aws.neon.tech/db?sslmode=require")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgres://u:p@ep-x.aws.neon.tech/db")
    s = Settings(_env_file=None)
    assert s.database_url.startswith("postgresql+psycopg://u:p@ep-x.us-east-1")
    # Never picked up implicitly; scripts/with-neon.sh sets it on purpose.
    assert s.migration_database_url is None


def test_planner_prefixed_url_wins(monkeypatch):
    monkeypatch.setenv("PLANNER_DATABASE_URL", "postgresql+psycopg:///local")
    monkeypatch.setenv("DATABASE_URL", "postgresql://remote/db")
    assert Settings(_env_file=None).database_url == "postgresql+psycopg:///local"
