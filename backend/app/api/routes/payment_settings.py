from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_organization, get_session
from app.models.entities import Organization
from app.schemas.payments import PaymentSettingsRead, PaymentSettingsUpdate

router = APIRouter(prefix="/payment-settings", tags=["payment-settings"])


def _read(organization: Organization) -> PaymentSettingsRead:
    configured = bool(organization.bank_account_name and organization.bank_iban)
    return PaymentSettingsRead(
        account_name=organization.bank_account_name,
        iban=organization.bank_iban,
        bic=organization.bank_bic,
        configured=configured,
        include_payment_link=organization.message_include_payment_link,
        include_payment_qr=organization.message_include_payment_qr,
    )


@router.get("", response_model=PaymentSettingsRead)
async def get_payment_settings(
    organization: Organization = Depends(get_organization),
) -> PaymentSettingsRead:
    return _read(organization)


@router.put("", response_model=PaymentSettingsRead)
async def update_payment_settings(
    payload: PaymentSettingsUpdate,
    organization: Organization = Depends(get_organization),
    session: AsyncSession = Depends(get_session),
) -> PaymentSettingsRead:
    organization.bank_account_name = payload.account_name
    organization.bank_iban = payload.iban
    organization.bank_bic = payload.bic
    if not payload.include_payment_link and not payload.include_payment_qr:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enable at least the payment link or the payment QR code",
        )
    organization.message_include_payment_link = payload.include_payment_link
    organization.message_include_payment_qr = payload.include_payment_qr
    await session.flush()
    return _read(organization)
