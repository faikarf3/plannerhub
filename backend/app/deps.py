import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.actions import ActionContext
from app.config import get_settings
from app.db import get_session
from app.timeutil import utcnow

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, reason)


def require_token(
    request: Request,
    # Declared so /docs shows the Authorize button; the header is checked by hand
    # below to give a specific reason (these get debugged from a phone Shortcut).
    _creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    header = request.headers.get("authorization")
    if not header:
        raise _unauthorized("missing Authorization header")
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        raise _unauthorized("Authorization header must start with 'Bearer ' (then the token)")
    token = token.strip()
    if not token:
        raise _unauthorized("no token after 'Bearer '")
    if not hmac.compare_digest(token.encode(), get_settings().api_token.encode()):
        raise _unauthorized("token doesn't match this server's token")


SessionDep = Annotated[Session, Depends(get_session)]


def get_ctx(session: SessionDep) -> ActionContext:
    return ActionContext(session=session, now=utcnow())


CtxDep = Annotated[ActionContext, Depends(get_ctx)]
