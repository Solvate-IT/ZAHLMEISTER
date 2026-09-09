from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import get_organization
from app.db.session import SessionLocal
from app.models.entities import Organization, Participant, ParticipantList
from app.schemas.imports import ImportCommitRequest, ImportCommitResponse, ImportPreview
from app.services.channel_strategy import reset_channel_knowledge
from app.services.imports import ImportParseError, parse_import
from app.services.plans import FREE_PARTICIPANTS_PER_LIST, is_pro

router = APIRouter(prefix="/participant-lists", tags=["participant-lists"])


def _email_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _phone_key(value: str | None) -> str:
    return "".join(char for char in (value or "") if char.isdigit())


async def _owned_list(
    session, organization: Organization, list_id: UUID, *, for_update: bool = False
) -> ParticipantList:
    item = await session.get(ParticipantList, list_id, with_for_update=for_update)
    if item is None or item.organization_id != organization.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Participant list not found"
        )
    return item


@router.post("/import-preview", response_model=ImportPreview)
async def import_preview(
    file: UploadFile = File(...),
    organization: Organization = Depends(get_organization),
) -> ImportPreview:
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        return parse_import(file.filename or "upload", file.content_type, data)
    except ImportParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/{list_id}/import", response_model=ImportCommitResponse)
async def commit_import(
    list_id: UUID,
    payload: ImportCommitRequest,
    organization: Organization = Depends(get_organization),
) -> ImportCommitResponse:
    async with SessionLocal.begin() as session:
        participant_list = await _owned_list(session, organization, list_id, for_update=True)
        existing_rows = (
            await session.execute(
                select(Participant)
                .where(Participant.list_id == participant_list.id)
                .order_by(Participant.created_at)
                .with_for_update()
            )
        ).scalars().all()
        initial_count = len(existing_rows)
        pro = await is_pro(session, organization.id)

        by_email = {_email_key(row.email): row for row in existing_rows if _email_key(row.email)}
        by_phone = {_phone_key(row.phone): row for row in existing_rows if _phone_key(row.phone)}
        new_rows: list[Participant] = []
        updated_ids: set[UUID] = set()
        skipped = 0

        for item in payload.participants:
            email = str(item.email).strip().lower() if item.email else None
            phone = item.phone.strip() if item.phone else None
            email_key = _email_key(email)
            phone_key = _phone_key(phone)
            email_match = by_email.get(email_key) if email_key else None
            phone_match = by_phone.get(phone_key) if phone_key else None

            if email_match is not None and phone_match is not None and email_match.id != phone_match.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Imported email and phone belong to different existing participants",
                )

            target = email_match or phone_match
            if target is not None:
                changed = False
                old_email = target.email
                old_phone = target.phone
                if target.name != item.name:
                    target.name = item.name
                    changed = True
                if email and target.email != email:
                    target.email = email
                    changed = True
                if phone and target.phone != phone:
                    target.phone = phone
                    changed = True
                if changed:
                    if _email_key(old_email) != _email_key(target.email):
                        await reset_channel_knowledge(session, target.id, "email")
                    if _phone_key(old_phone) != _phone_key(target.phone):
                        await reset_channel_knowledge(session, target.id, "whatsapp")
                        await reset_channel_knowledge(session, target.id, "sms")
                    updated_ids.add(target.id)
                else:
                    skipped += 1
                if email_key:
                    by_email[email_key] = target
                if phone_key:
                    by_phone[phone_key] = target
                continue

            if not pro and initial_count + len(new_rows) + 1 > FREE_PARTICIPANTS_PER_LIST:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Free plan supports up to {FREE_PARTICIPANTS_PER_LIST} participants per list",
                )
            row = Participant(
                list_id=participant_list.id,
                name=item.name,
                email=email,
                phone=phone,
            )
            session.add(row)
            await session.flush()
            new_rows.append(row)
            if email_key:
                by_email[email_key] = row
            if phone_key:
                by_phone[phone_key] = row

        return ImportCommitResponse(
            imported_count=len(new_rows),
            updated_count=len(updated_ids),
            skipped_count=skipped,
        )
