from fastapi import APIRouter

from app.api.routes.public_api import router as public_api_routes

public_api_router = APIRouter(tags=["public-api"])
public_api_router.include_router(public_api_routes)
