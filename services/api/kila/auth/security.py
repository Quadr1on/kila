"""Password hashing (bcrypt) and signed session cookies (itsdangerous). Local only."""

from __future__ import annotations

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from kila.settings import get_settings

COOKIE_NAME = "kila_session"
ROLES = ("engineer", "reviewer", "admin")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except ValueError:
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="kila-session")


def make_session_token(user_id: int) -> str:
    return _serializer().dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    max_age = get_settings().app["auth"]["session_max_age_s"]
    try:
        data = _serializer().loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("uid")
