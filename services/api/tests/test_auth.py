from __future__ import annotations

from tests.conftest import PASSWORD


def test_seeded_users_and_roles(client_for):
    for name in ("engineer", "reviewer", "admin"):
        me = client_for(name).get("/auth/me").json()
        assert me["name"] == name and me["role"] == name


def test_bad_password_rejected_and_logged(app_env, client_for):
    _, c = app_env
    assert c.post("/auth/login", json={"username": "engineer", "password": "wrong"}).status_code == 401
    events = client_for("admin").get("/ledger/events?event_type=auth.login_failed").json()
    assert events and events[0]["payload"]["username"] == "engineer"


def test_session_cookie_is_httponly(app_env):
    _, c = app_env
    r = c.post("/auth/login", json={"username": "reviewer", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "kila_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_forged_cookie_rejected(app_env):
    _, c = app_env
    c.cookies.set("kila_session", "eyJ1aWQiOjN9.forged.sig")
    assert c.get("/auth/me").status_code == 401


def test_logout(client_for):
    c = client_for("engineer")
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/auth/me").status_code == 401


def test_passwords_are_bcrypt(app_env):
    from sqlmodel import Session, select

    from kila.db.models import User
    from kila.db.session import get_engine

    with Session(get_engine()) as s:
        for u in s.exec(select(User)).all():
            assert u.password_hash.startswith("$2") and PASSWORD not in u.password_hash
