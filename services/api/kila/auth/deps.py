from __future__ import annotations

from collections.abc import Callable

from fastapi import Cookie, Depends, HTTPException, status
from sqlmodel import Session

from kila.auth.security import COOKIE_NAME, read_session_token
from kila.db.models import User
from kila.db.session import get_session


def current_user(
    session: Session = Depends(get_session),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    uid = read_session_token(token) if token else None
    user = session.get(User, uid) if uid is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user


def require_role(*roles: str) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role: {', '.join(roles)}")
        return user

    return dep
