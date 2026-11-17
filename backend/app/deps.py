import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.actions import ActionContext
from app.config import get_settings
from app.db import get_session
from app.timeutil import utcnow

_bearer = HTTPBearer(auto_error=False)


def require_token(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = get_settings().api_token
    if creds is None or not hmac.compare_digest(creds.credentials, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")


SessionDep = Annotated[Session, Depends(get_session)]


def get_ctx(session: SessionDep) -> ActionContext:
    return ActionContext(session=session, now=utcnow())


CtxDep = Annotated[ActionContext, Depends(get_ctx)]
