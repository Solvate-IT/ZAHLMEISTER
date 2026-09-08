from fastapi import APIRouter

from app.api.routes.account import router as account_router
from app.api.routes.admin import router as admin_router
from app.api.routes.api_access import router as api_access_router
from app.api.routes.auth import router as auth_router
from app.api.routes.bank_imports import router as bank_imports_router
from app.api.routes.bank_sync import router as bank_sync_router
from app.api.routes.billing import router as billing_router
from app.api.routes.collections import router as collections_router
from app.api.routes.communication_settings import router as communication_settings_router
from app.api.routes.communications import router as communications_router
from app.api.routes.health import router as health_router
from app.api.routes.imports import router as imports_router
from app.api.routes.message_templates import router as message_templates_router
from app.api.routes.online_payments import router as online_payments_router
from app.api.routes.participant_lists import router as participant_lists_router
from app.api.routes.payment_settings import router as payment_settings_router
from app.api.routes.public_contact import router as public_contact_router
from app.api.routes.public_payments import router as public_payments_router
from app.api.routes.reports import router as reports_router
from app.api.routes.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(account_router)
api_router.include_router(api_access_router)
api_router.include_router(billing_router)
api_router.include_router(participant_lists_router)
api_router.include_router(imports_router)
api_router.include_router(bank_imports_router)
api_router.include_router(bank_sync_router)
api_router.include_router(collections_router)
api_router.include_router(reports_router)
api_router.include_router(communications_router)
api_router.include_router(communication_settings_router)
api_router.include_router(message_templates_router)
api_router.include_router(payment_settings_router)
api_router.include_router(online_payments_router)
api_router.include_router(public_payments_router)
api_router.include_router(public_contact_router)
api_router.include_router(webhooks_router)
