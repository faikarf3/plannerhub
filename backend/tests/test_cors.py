import re

import pytest

from app.config import Settings

ALLOWED = [
    "http://localhost:5173",
    "http://localhost",
    "http://127.0.0.1:8080",
    "https://planner-hub-97a70d.web.app",
    "https://planner-hub-97a70d.firebaseapp.com",
]
REFUSED = [
    "https://evil.example",
    "https://localhost:5173",            # dev origins are http only
    "http://localhost.evil.example",
    "https://planner-hub-97a70d.web.app.evil.example",
    "https://other-project.web.app",
    "http://planner-hub-97a70d.web.app",  # hosting is https only
]


def _preflight(client, origin, method="POST"):
    return client.options("/log", headers={
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "authorization,content-type",
    })


@pytest.mark.parametrize("origin", ALLOWED)
def test_preflight_allowed(client, origin):
    r = _preflight(client, origin)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    allowed_headers = r.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed_headers and "content-type" in allowed_headers


@pytest.mark.parametrize("origin", REFUSED)
def test_preflight_refused(client, origin):
    r = _preflight(client, origin)
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE"])
def test_methods_allowed(client, method):
    r = _preflight(client, "http://localhost:5173", method)
    assert r.status_code == 200
    assert method in r.headers["access-control-allow-methods"]


def test_simple_request_and_errors_carry_origin(client):
    origin = "http://localhost:5173"
    ok = client.get("/categories", headers={"Origin": origin})
    assert ok.headers["access-control-allow-origin"] == origin
    # The browser must be able to read 401 bodies too, to show the reason.
    denied = client.get("/categories", headers={"Origin": origin, "Authorization": "Bearer x"})
    assert denied.status_code == 401
    assert denied.headers["access-control-allow-origin"] == origin


def test_default_regex_is_a_full_match_list():
    pattern = re.compile(Settings(_env_file=None, api_token="x").cors_origin_regex)
    assert all(pattern.fullmatch(o) for o in ALLOWED)
    assert not any(pattern.fullmatch(o) for o in REFUSED)


def test_regex_comes_from_setting(monkeypatch):
    monkeypatch.setenv("PLANNER_CORS_ORIGIN_REGEX", r"https://example\.com")
    assert Settings(_env_file=None, api_token="x").cors_origin_regex == r"https://example\.com"
