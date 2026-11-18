import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def anon(client):
    # `client` installs the DB override; this one sends no default auth header.
    return TestClient(app)


@pytest.mark.parametrize("header, reason", [
    (None, "missing Authorization header"),
    ("test-token", "must start with 'Bearer '"),
    ("Bearer ", "no token after 'Bearer '"),
    ("Bearer wrong", "doesn't match"),
])
def test_auth_errors_say_why(anon, header, reason):
    headers = {"Authorization": header} if header is not None else {}
    r = anon.post("/log", json={"text": "climb 1h"}, headers=headers)
    assert r.status_code == 401
    assert reason in r.json()["message"]


def test_token_tolerates_stray_whitespace(anon):
    r = anon.get("/categories", headers={"Authorization": "bearer  test-token "})
    assert r.status_code == 200


def test_validation_error_has_message(client):
    r = client.post("/log", json={"txt": "oops"})
    assert r.status_code == 422
    assert r.json()["message"].startswith("bad request: text")
