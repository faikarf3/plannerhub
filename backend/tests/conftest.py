import os

os.environ["PLANNER_DATABASE_URL"] = os.environ.get(
    "PLANNER_TEST_DATABASE_URL", "postgresql+psycopg:///planner_hub_test"
)
os.environ["PLANNER_API_TOKEN"] = "test-token"
# Never call the real model from tests (backend/.env may hold a key); tests that
# need extraction override get_extractor with a fake.
os.environ["PLANNER_GEMINI_API_KEY"] = ""

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402

URL = os.environ["PLANNER_DATABASE_URL"]


@pytest.fixture(scope="session")
def engine():
    """Fresh schema from the real migrations, so tests also cover the migration."""
    cfg = Config("alembic.ini")
    cfg.attributes["url"] = URL
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """Each test runs in an outer transaction that is rolled back afterwards;
    the app's commits become savepoint releases."""
    with engine.connect() as conn:
        outer = conn.begin()
        sess = Session(bind=conn, join_transaction_mode="create_savepoint",
                       expire_on_commit=False)
        try:
            yield sess
        finally:
            sess.close()
            outer.rollback()


@pytest.fixture
def client(session):
    def _session():
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise

    app.dependency_overrides[get_session] = _session
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as c:
        yield c
    app.dependency_overrides.clear()
