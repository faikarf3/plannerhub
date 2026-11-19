"""Who is calling: the owner token (Siri Shortcut, admin) or a Firebase ID token
(the app). Pipeline keys for POST /events are handled in deps.pipeline_source.

Single user: a Firebase token is accepted only for a verified, allow-listed email.
Every refusal says why, in the style of the other 401s.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from fastapi import status

from app.config import Settings


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Principal:
    kind: Literal["owner", "firebase"]
    email: str | None = None
    uid: str | None = None


OWNER = Principal("owner")


def looks_like_jwt(token: str) -> bool:
    return token.count(".") == 2


@lru_cache
def _google_request():
    """HTTP transport for Google's public signing certs, cached per their
    Cache-Control headers so most requests don't refetch them."""
    import cachecontrol
    import google.auth.transport.requests
    import requests

    return google.auth.transport.requests.Request(
        session=cachecontrol.CacheControl(requests.Session())
    )


def _verify_with_google(token: str, project_id: str) -> Mapping[str, Any]:
    """The only call to Google. Tests replace this function."""
    from google.oauth2 import id_token

    return id_token.verify_firebase_token(
        token, _google_request(), audience=project_id, clock_skew_in_seconds=10
    )


def _reason(error: Exception) -> str:
    text = str(error)
    if text.startswith("Token expired"):
        return "Firebase sign-in expired; sign in again"
    if "wrong audience" in text:
        return "Firebase token is for a different project"
    if text.startswith("Token used too early"):
        return "Firebase token isn't valid yet; check the device clock"
    if "signature" in text or "Certificate for key id" in text:
        return "Firebase token signature is invalid"
    return "not a valid Firebase sign-in token"


def firebase_principal(token: str, settings: Settings) -> Principal:
    from google.auth import exceptions as google_errors

    project = settings.firebase_project_id
    if not project:
        raise AuthError("Firebase sign-in isn't set up on this server")
    allowed = settings.allowed_email_set
    if not allowed:
        raise AuthError("no accounts are allowed to sign in yet (PLANNER_ALLOWED_EMAILS is empty)")

    try:
        claims = _verify_with_google(token, project)
    except google_errors.TransportError as e:
        raise AuthError("couldn't reach Google to check the sign-in; try again",
                        status.HTTP_503_SERVICE_UNAVAILABLE) from e
    except (ValueError, google_errors.GoogleAuthError) as e:
        raise AuthError(_reason(e)) from e

    if claims.get("iss") != f"https://securetoken.google.com/{project}":
        raise AuthError("Firebase token is for a different project")
    email = (claims.get("email") or "").strip()
    if not email:
        raise AuthError("this sign-in has no email address")
    if claims.get("email_verified") is not True:
        raise AuthError(f"{email} isn't verified yet")
    if email.lower() not in allowed:
        raise AuthError(f"{email} isn't allowed to use Planner Hub")
    return Principal("firebase", email=email, uid=claims.get("sub"))
