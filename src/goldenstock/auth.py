"""Revocable server-side sessions and tenant/owner checks shared by all routes."""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from goldenstock.models import User, LoginSession, AuditEvent

COOKIE = 'gs_session'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password, salt=None):
    if not 12 <= len(password) <= 128:
        raise HTTPException(422, 'Password must contain 12–128 characters')
    salt = salt or secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**15,
                         r=8, p=1, maxmem=64*1024*1024).hex()
    return f'scrypt${salt}${key}'


def verify_password(password, stored):
    try:
        return hmac.compare_digest(hash_password(password, stored.split('$')[1]), stored)
    except (HTTPException, ValueError, IndexError):
        return False


@dataclass(frozen=True)
class Actor:
    id: str
    org_id: str
    login: str
    account_admin: bool
    csrf: str


def authenticate(request: Request, mutation=False):
    token = request.cookies.get(COOKIE, '')
    with Session(request.app.state.engine) as db:
        session = db.get(LoginSession, digest(token)) if token else None
        user = db.get(User, session.user_id) if session else None
        if not session or session.expires <= time.time() or not user or not user.active:
            raise HTTPException(401, 'Please sign in')
        if mutation:
            check_origin(request)
            if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session.csrf):
                raise HTTPException(403, 'Invalid CSRF token')
        return Actor(user.id, user.org_id, user.login, user.account_admin, session.csrf)


def check_origin(request):
    # Pin the origin in configuration, never trust the supplied Host header.
    if request.headers.get('origin') != request.app.state.settings.public_url:
        raise HTTPException(403, 'Untrusted request origin')


def visible(cls, actor):
    return (cls.org_id == actor.org_id) & or_(cls.owner_id == actor.id, cls.shared.is_(True))


def owned(db, cls, object_id, actor, write=False):
    obj = db.scalar(select(cls).where(cls.id == object_id, visible(cls, actor)))
    if obj is None or (write and obj.owner_id != actor.id):
        raise HTTPException(404, 'Object not found')
    return obj


def audit(db, actor, action, target, detail=''):
    db.add(AuditEvent(org_id=actor.org_id, actor_id=actor.id, action=action,
                      target=target, detail=detail))
