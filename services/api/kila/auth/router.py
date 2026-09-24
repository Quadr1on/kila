from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlmodel import Session, select

from kila import ledger
from kila.auth.deps import current_user
from kila.auth.security import COOKIE_NAME, check_password, make_session_token
from kila.db.models import User
from kila.db.session import get_session
from kila.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    role: str


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, response: Response, session: Session = Depends(get_session)) -> UserOut:
    user = session.exec(select(User).where(User.name == body.username)).first()
    if user is None or not check_password(body.password, user.password_hash):
        ledger.append(body.username[:64], "auth.login_failed", {"username": body.username[:64]})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    s = get_settings()
    response.set_cookie(
        COOKIE_NAME, make_session_token(user.id), httponly=True, samesite="lax",
        secure=s.cookie_secure, max_age=s.app["auth"]["session_max_age_s"], path="/",
    )
    ledger.append(user.name, "auth.login", {"user_id": user.id, "role": user.role})
    return UserOut(id=user.id, name=user.name, role=user.role)


@router.post("/logout", status_code=204)
def logout(response: Response, user: User = Depends(current_user)) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
    ledger.append(user.name, "auth.logout", {"user_id": user.id})


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, name=user.name, role=user.role)
