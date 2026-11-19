"""Firebase ID tokens for the app. Google is never called: `_verify_with_google`
is replaced by a fake that returns claims or raises google-auth's own errors."""

import pytest
from fastapi.testclient import TestClient
from google.auth import exceptions as google_errors

from app.config import get_settings
from app.main import app

PROJECT = "planner-hub-97a70d"
TOKEN = "header.payload.signature"  # shape only; the fake decides what it means
ME = "owner@example.com"


def claims(**overrides):
    return {
        "iss": f"https://securetoken.google.com/{PROJECT}", "aud": PROJECT,
        "sub": "firebase-uid-1", "email": ME, "email_verified": True, **overrides,
    }


@pytest.fixture
def allow(monkeypatch):
    monkeypatch.setattr(get_settings(), "allowed_emails", f"someone@example.com, {ME.upper()}")


@pytest.fixture
def google(monkeypatch):
    """Set `google.result` to claims or an exception; records each call."""
    class Fake:
        result: object = claims()
        calls: list = []

        def __call__(self, token, project_id):
            self.calls.append((token, project_id))
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr("app.auth._verify_with_google", fake)
    return fake


@pytest.fixture
def app_client(client):
    """Same DB as `client`, but sending a Firebase token instead of the owner token."""
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_allowed_firebase_user_gets_in(allow, google, app_client):
    r = app_client.get("/categories")
    assert r.status_code == 200, r.text
    assert google.calls == [(TOKEN, PROJECT)]
    me = app_client.get("/me").json()
    assert me == {"auth": "firebase", "email": ME, "uid": "firebase-uid-1"}


def test_firebase_user_can_write_through_action_layer(allow, google, app_client):
    r = app_client.post("/log", json={"text": "climb 1h"})
    assert r.status_code == 200 and r.json()["actions"]


def test_owner_token_still_works_without_google(client, google):
    assert client.get("/me").json() == {"auth": "owner", "email": None, "uid": None}
    assert google.calls == []


@pytest.mark.parametrize("result, status, reason", [
    (ValueError("Token expired, 100 < 200"), 401, "sign-in expired"),
    (ValueError("Token has wrong audience other, expected one of ['planner-hub-97a70d']"),
     401, "different project"),
    (ValueError("Token used too early, 200 < 100. Check that your computer's clock"),
     401, "check the device clock"),
    (ValueError("Could not verify token signature."), 401, "signature is invalid"),
    (ValueError("Wrong number of segments in token: b'x'"), 401, "not a valid Firebase"),
    (google_errors.TransportError("Could not fetch certificates"), 503, "couldn't reach Google"),
    (claims(iss="https://securetoken.google.com/other"), 401, "different project"),
    (claims(email_verified=False), 401, f"{ME} isn't verified"),
    (claims(email=None), 401, "no email address"),
    (claims(email="stranger@example.com"), 401, "stranger@example.com isn't allowed"),
])
def test_refusals_say_why(allow, google, app_client, result, status, reason):
    google.result = result
    r = app_client.get("/today")
    assert r.status_code == status
    assert reason in r.json()["message"]


def test_nobody_allowed_by_default(google, app_client):
    r = app_client.get("/today")
    assert r.status_code == 401
    assert "PLANNER_ALLOWED_EMAILS is empty" in r.json()["message"]
    assert google.calls == []


def test_no_project_configured(allow, google, app_client, monkeypatch):
    monkeypatch.setattr(get_settings(), "firebase_project_id", None)
    assert "isn't set up" in app_client.get("/today").json()["message"]


def test_non_jwt_wrong_token_keeps_old_message(allow, google, client):
    r = client.get("/today", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.json()["message"] == "token doesn't match this server's token"
    assert google.calls == []


def test_pipeline_route_does_not_accept_firebase(allow, google, app_client):
    r = app_client.post("/events", json={"type": "run_finished", "data": {"count": 1}})
    assert r.status_code == 401
    assert google.calls == []


def test_allowed_email_set_parsing(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "allowed_emails", " A@x.com ,, b@Y.com ")
    assert s.allowed_email_set == {"a@x.com", "b@y.com"}
