"""Account management is separate from access to financial objects."""
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from goldenstock.auth import COOKIE, authenticate, check_origin, digest, hash_password, verify_password, owned, visible, audit
from goldenstock.models import User, LoginSession, WorkspaceModel

router = APIRouter(prefix='/api/v1')


class Credentials(BaseModel):
    login: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9@._-]+$')
    password: str = Field(min_length=12, max_length=128)


class NewModel(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class Visibility(BaseModel):
    shared: bool
    revision: int = Field(ge=1)


class ActiveState(BaseModel):
    active: bool


class LoginLimiter:
    """Bounded per-IP throttling for the single-process local pilot."""
    def __init__(self):
        self.lock = Lock()
        self.attempts = defaultdict(deque)

    def check(self, key):
        now = time.monotonic()
        with self.lock:
            for old in list(self.attempts):
                if not self.attempts[old] or self.attempts[old][-1] < now-300:
                    del self.attempts[old]
            queue = self.attempts[key]
            while queue and queue[0] < now-300:
                queue.popleft()
            if len(queue) >= 30 or len(self.attempts) > 10000:
                raise HTTPException(429, 'Too many sign-in attempts; try again in five minutes')
            queue.append(now)


@router.post('/auth/login')
def login(data: Credentials, request: Request):
    check_origin(request)
    request.app.state.login_limiter.check(request.client.host if request.client else 'local')
    with Session(request.app.state.engine) as db, db.begin():
        user = db.scalar(select(User).where(User.login == data.login.lower()))
        # Equal-cost verification for unknown accounts.
        stored = user.password_hash if user else request.app.state.dummy_password
        valid = verify_password(data.password, stored)
        if not user or not valid or not user.active:
            raise HTTPException(401, 'Invalid credentials')
        db.execute(delete(LoginSession).where(LoginSession.expires < time.time()))
        old = request.cookies.get(COOKIE)
        if old:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(old)))
        token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
        db.add(LoginSession(token_hash=digest(token), user_id=user.id, csrf=csrf, expires=time.time()+8*3600))
        response = JSONResponse({'csrf': csrf})
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', secure=request.app.state.settings.secure_cookie, max_age=8*3600)
        return response


@router.get('/auth/me')
def me(request: Request):
    return authenticate(request).__dict__


@router.post('/auth/logout')
def logout(request: Request):
    authenticate(request, True)
    with Session(request.app.state.engine) as db, db.begin():
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(request.cookies[COOKIE])))
    response = JSONResponse({'ok': True})
    response.delete_cookie(COOKIE)
    return response


@router.get('/users')
def users(request: Request):
    actor = authenticate(request)
    if not actor.account_admin:
        raise HTTPException(403, 'Account administrator required')
    with Session(request.app.state.engine) as db:
        return [{'id': u.id, 'login': u.login, 'active': u.active, 'account_admin': u.account_admin}
                for u in db.scalars(select(User).where(User.org_id == actor.org_id).order_by(User.login))]


@router.post('/users', status_code=201)
def create_user(data: Credentials, request: Request):
    actor = authenticate(request, True)
    if not actor.account_admin:
        raise HTTPException(403, 'Account administrator required')
    try:
        with Session(request.app.state.engine) as db, db.begin():
            user = User(org_id=actor.org_id, login=data.login.lower(), password_hash=hash_password(data.password))
            db.add(user)
            db.flush()
            audit(db, actor, 'account.create', user.id)
            return {'id': user.id, 'login': user.login}
    except IntegrityError:
        raise HTTPException(409, 'Login is unavailable') from None


@router.patch('/users/{user_id}')
def set_active(user_id: str, data: ActiveState, request: Request):
    actor = authenticate(request, True)
    if not actor.account_admin:
        raise HTTPException(403, 'Account administrator required')
    with Session(request.app.state.engine) as db, db.begin():
        user = db.scalar(select(User).where(User.id == user_id, User.org_id == actor.org_id))
        if not user:
            raise HTTPException(404, 'Account not found')
        if user.account_admin:
            raise HTTPException(409, 'Manage administrators using the local operator CLI')
        user.active = data.active
        if not data.active:
            db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        audit(db, actor, 'account.active', user.id, str(data.active))
    return {'ok': True}


def model_dict(model):
    return {k: getattr(model, k) for k in ('id', 'owner_id', 'title', 'shared', 'revision')}


@router.get('/models')
def list_models(request: Request, q: str = ''):
    actor = authenticate(request)
    with Session(request.app.state.engine) as db:
        return [model_dict(m) for m in db.scalars(select(WorkspaceModel).where(
            visible(WorkspaceModel, actor), WorkspaceModel.title.icontains(q[:160], autoescape=True)).limit(200))]


@router.post('/models', status_code=201)
def create_model(data: NewModel, request: Request):
    actor = authenticate(request, True)
    with Session(request.app.state.engine) as db, db.begin():
        model = WorkspaceModel(org_id=actor.org_id, owner_id=actor.id, title=data.title.strip())
        db.add(model)
        db.flush()
        audit(db, actor, 'model.create', model.id)
        return model_dict(model)


@router.get('/models/{model_id}')
def get_model(model_id: str, request: Request):
    actor = authenticate(request)
    with Session(request.app.state.engine) as db:
        return model_dict(owned(db, WorkspaceModel, model_id, actor))


@router.patch('/models/{model_id}/visibility')
def share_model(model_id: str, data: Visibility, request: Request):
    actor = authenticate(request, True)
    with Session(request.app.state.engine) as db, db.begin():
        model = owned(db, WorkspaceModel, model_id, actor, True)
        result = db.execute(update(WorkspaceModel).where(WorkspaceModel.id == model.id,
            WorkspaceModel.revision == data.revision).values(shared=data.shared, revision=data.revision+1))
        if not result.rowcount:
            raise HTTPException(409, 'Revision changed; refresh first')
        # Only draft titles are shared here: no attached financial evidence exists yet.
        audit(db, actor, 'model.visibility', model.id, f'revision={data.revision+1};shared={data.shared};title={model.title}')
        return model_dict(model)
