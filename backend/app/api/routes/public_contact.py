import logging

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import settings
from app.schemas.contact import ContactRequest
from app.services.platform_mail import send_platform_mail

router = APIRouter(prefix="/public/contact", tags=["public-contact"])
logger = logging.getLogger("zahlmeister.contact")


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def submit_contact(payload: ContactRequest) -> Response:
    # Honeypot: silently accept obvious bot submissions without sending mail.
    if payload.website.strip():
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    subject = f"Zahlmeister contact: {payload.subject}"
    body = "\n".join(
        [
            f"Name: {payload.name}",
            f"Email: {payload.email}",
            f"Locale: {payload.locale}",
            "",
            payload.message,
        ]
    )
    try:
        await send_platform_mail(
            subject=subject,
            recipient=settings.contact_recipient,
            body=body,
        )
    except Exception as exc:
        logger.exception("Contact message delivery failed", extra={"event": "contact_delivery_failed"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Contact service is temporarily unavailable",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
