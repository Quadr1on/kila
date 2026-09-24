"""Idempotent seed: buckets + demo users. Passwords come from KILA_SEED_PASSWORD."""

from __future__ import annotations

from sqlmodel import Session, select

from kila import ledger
from kila.auth.security import hash_password
from kila.db.models import Bucket, User
from kila.db.session import get_engine
from kila.settings import get_settings


def seed() -> dict[str, list[str]]:
    s = get_settings()
    created: dict[str, list[str]] = {"buckets": [], "users": []}
    with Session(get_engine()) as session:
        for name in s.app["storage"]["buckets"]:
            if not session.exec(select(Bucket).where(Bucket.name == name)).first():
                session.add(Bucket(name=name, is_public=False))
                created["buckets"].append(name)
        for u in s.app["auth"]["seed_users"]:
            if not session.exec(select(User).where(User.name == u["name"])).first():
                session.add(User(name=u["name"], role=u["role"], password_hash=hash_password(s.seed_password)))
                created["users"].append(u["name"])
        session.commit()
    if created["buckets"] or created["users"]:
        ledger.append("system", "system.seed", created)
    return created


if __name__ == "__main__":
    from kila.db.session import run_migrations

    run_migrations()
    print(seed())
