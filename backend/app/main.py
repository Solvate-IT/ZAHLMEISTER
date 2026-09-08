from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.public_router import public_api_router
from app.api.router import api_router
from app.core.config import settings
from app.core.observability import RequestLoggingMiddleware, configure_logging
from app.services.platform_admin import bootstrap_platform_admin

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    security_errors = settings.production_security_errors()
    if security_errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(security_errors))
    await bootstrap_platform_admin()
    yield


app = FastAPI(
    title="Zahlmeister API",
    version="0.19.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Admin-Request"],
)
app.include_router(api_router, prefix="/api/v1")
app.include_router(public_api_router, prefix="/api/public/v1")
