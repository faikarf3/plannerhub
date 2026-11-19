import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.actions import ActionContext
from app.actions.pipelines import hash_key
from app.config import get_settings
from app.db import get_session
from app.models import PipelineKey
from app.timeutil import utcnow

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, reason)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization")
    if not header:
        raise _unauthorized("missing Authorization header")
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        raise _unauthorized("Authorization header must start with 'Bearer ' (then the token)")
    token = token.strip()
    if not token:
        raise _unauthorized("no token after 'Bearer '")
    return token


def _is_owner(token: str) -> bool:
    return hmac.compare_digest(token.encode(), get_settings().api_token.encode())


def require_token(
    request: Request,
    # Declared so /docs shows the Authorize button; the header is checked by hand
    # below to give a specific reason (these get debugged from a phone Shortcut).
    _creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    if not _is_owner(_bearer_token(request)):
        raise _unauthorized("token doesn't match this server's token")


SessionDep = Annotated[Session, Depends(get_session)]


def get_ctx(session: SessionDep) -> ActionContext:
    return ActionContext(session=session, now=utcnow())


CtxDep = Annotated[ActionContext, Depends(get_ctx)]


def pipeline_source(
    request: Request,
    session: SessionDep,
    _creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str | None:
    """Auth for POST /events: a pipeline's own key (returns its source) or the
    owner token (returns None: any source, named in the body)."""
    token = _bearer_token(request)
    if _is_owner(token):
        return None
    key = session.scalar(select(PipelineKey).where(
        PipelineKey.key_hash == hash_key(token), PipelineKey.revoked_at.is_(None)))
    if key is None:
        raise _unauthorized("not a known pipeline key (or it was revoked)")
    return key.source


PipelineSourceDep = Annotated[str | None, Depends(pipeline_source)]
