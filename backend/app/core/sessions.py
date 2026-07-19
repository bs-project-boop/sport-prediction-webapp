from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_session_token, hash_session_token
from app.models import AuthSession


class SessionStore:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = timedelta(seconds=ttl_seconds)

    def create(self, db: Session, client_key: str) -> str:
        token = generate_session_token()
        now = datetime.now(timezone.utc)
        db.add(AuthSession(token_hash=hash_session_token(token), client_key=client_key, expires_at=now + self.ttl))
        db.commit()
        return token

    def get(self, db: Session, token: str | None) -> AuthSession | None:
        if not token:
            return None
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_session_token(token)))
        now = datetime.now(timezone.utc)
        if not row or row.revoked_at:
            return None
        expiry = row.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= now:
            return None
        row.last_seen_at = now
        db.commit()
        return row

    def revoke(self, db: Session, token: str | None) -> None:
        if not token:
            return
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_session_token(token)))
        if row:
            row.revoked_at = datetime.now(timezone.utc)
            db.commit()

    def rotate(self, db: Session, token: str, client_key: str) -> str | None:
        self.revoke(db, token)
        return self.create(db, client_key)
