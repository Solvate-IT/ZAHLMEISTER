from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.public_router import public_api_router
from app.api.router import api_router
from app.core.config import settings
from app.core.observability import RequestLoggingMiddleware, configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    security_errors = settings.production_security_errors()
    if security_errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(security_errors))
    yield


app = FastAPI(
    title="Zahlmeister API",
    version="0.18.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.include_router(api_router, prefix="/api/v1")
app.include_router(public_api_router, prefix="/api/public/v1")
