"""Application composition: authenticated workspace and separate health endpoints."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from goldenstock.config import Settings, get_settings
from goldenstock.db import make_engine
from goldenstock.health import inference_status, readiness
from goldenstock.accounts import router as accounts_router, LoginLimiter
from goldenstock.companies import router as companies_router
from goldenstock.documents import router as documents_router
from goldenstock.sources import router as sources_router
from goldenstock.facts import router as facts_router
from goldenstock.reviews import router as reviews_router
from goldenstock.ai_runs import router as ai_router
from goldenstock.knowledge import router as knowledge_router
from goldenstock.public_sources import router as public_router
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from goldenstock.auth import hash_password
import secrets


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="GoldenStock", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    app.state.settings = settings
    app.state.login_limiter = LoginLimiter()
    app.state.dummy_password = hash_password(secrets.token_urlsafe(24))
    app.include_router(accounts_router)
    app.include_router(companies_router)
    app.include_router(documents_router)
    app.include_router(sources_router)
    app.include_router(facts_router)
    app.include_router(reviews_router)
    app.include_router(ai_router)
    app.include_router(knowledge_router)
    app.include_router(public_router)
    app.add_middleware(RequestBodyLimitMiddleware,max_body_size=settings.max_file_bytes+65536)

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        status = await readiness(engine, settings)
        return JSONResponse(status, status_code=200 if status["status"] == "ready" else 503)

    @app.get("/api/v1/status")
    async def status():
        state = await readiness(engine, settings)
        state["inference"] = await inference_status(settings)
        state["stage"] = "workspace"
        state["financial_processing_enabled"] = False
        return state

    return app
