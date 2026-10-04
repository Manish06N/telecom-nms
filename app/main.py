"""The front door.

A request comes in here, passes middleware, then a route. The route calls a service.
The service decides. The database session commits only if the service did not raise.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.router import router as api_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.seed import seed
from app.db.session import SessionLocal
import app.models  # noqa: F401  # register tables before create_all
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telecom")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key in {"change-me", "change-me-to-a-long-random-string"} and not settings.debug:
        raise RuntimeError("Set a unique SECRET_KEY when DEBUG is false")
    if settings.auto_seed:
        db = SessionLocal()
        try:
            if settings.debug:
                Base.metadata.create_all(bind=db.get_bind())
            seed(db)
            db.commit()
        finally:
            db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        summary="Telecom customers, SIMs, network, tickets, and SLA.",
        description=(
            "Staff and customers share one API. What you can do depends on your role. "
            "Business rules live in app/services and app/domain. These routes only translate HTTP."
        ),
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials="*" not in origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(ws_router)

    @app.get("/health", tags=["Operations"])
    def health(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    except Exception:
        logger.warning("Prometheus metrics are unavailable")
    return app


app = create_app()
