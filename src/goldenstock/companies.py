"""Public catalog plus user-owned favorites; no fabricated market data."""
import time
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from goldenstock.auth import authenticate, audit
from goldenstock.models import Company, Favorite

router = APIRouter(prefix='/api/v1')


def company_dict(company, favorite=False):
    fresh = ('missing' if company.source_checked is None else
             'stale' if time.time()-company.source_checked > 90*86400 else 'current')
    return dict(id=company.id, name=company.name, identifier=company.identifier,
                candidate=company.candidate, favorite=favorite, source_url=company.source_url or None,
                freshness=fresh, source_checked=company.source_checked, summary=None, last_calculation='not_run')


@router.get('/companies')
def companies(request: Request, q: str = '', favorites: bool = False):
    actor = authenticate(request)
    with Session(request.app.state.engine) as db:
        saved = set(db.scalars(select(Favorite.company_id).where(Favorite.user_id == actor.id)))
        return [company_dict(c, c.id in saved) for c in db.scalars(select(Company).where(
            Company.name.icontains(q[:160], autoescape=True)).order_by(Company.name)) if not favorites or c.id in saved]


@router.get('/companies/{company_id}')
def company(company_id: str, request: Request):
    actor = authenticate(request)
    with Session(request.app.state.engine) as db:
        item = db.get(Company, company_id)
        if not item:
            raise HTTPException(404, 'Company not found')
        return company_dict(item, db.get(Favorite, (actor.id, company_id)) is not None)


@router.put('/favorites/{company_id}')
def favorite(company_id: str, request: Request):
    actor = authenticate(request, True)
    try:
        with Session(request.app.state.engine) as db, db.begin():
            if not db.get(Company, company_id):
                raise HTTPException(404, 'Company not found')
            if not db.get(Favorite, (actor.id, company_id)):
                db.add(Favorite(user_id=actor.id, company_id=company_id))
                audit(db, actor, 'favorite.add', company_id)
    except IntegrityError:
        pass  # Concurrent identical requests converge on the same favorite.
    return {'ok': True}


@router.delete('/favorites/{company_id}')
def unfavorite(company_id: str, request: Request):
    actor = authenticate(request, True)
    with Session(request.app.state.engine) as db, db.begin():
        item = db.get(Favorite, (actor.id, company_id))
        if item:
            db.delete(item)
            audit(db, actor, 'favorite.remove', company_id)
    return {'ok': True}
