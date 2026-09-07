from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import get_organization
from app.db.session import SessionLocal
from app.models.entities import Organization, Participant, ParticipantList
from app.schemas.imports import ImportCommitRequest, ImportCommitResponse, ImportPreview
from app.services.imports import ImportParseError, parse_import

router = APIRouter(prefix="/participant-lists", tags=["participant-lists"])


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
    # Reading is capped in memory; original upload is discarded after this request.
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
                select(Participant.name, Participant.email, Participant.phone).where(
                    Participant.list_id == participant_list.id
                )
            )
        ).all()
        existing = {
            (
                name.casefold(),
                (email or "").casefold(),
                "".join(char for char in (phone or "") if char.isdigit()),
            )
            for name, email, phone in existing_rows
        }

        imported = 0
        skipped = 0
        for item in payload.participants:
            key = (
                item.name.casefold(),
                (str(item.email) if item.email else "").casefold(),
                "".join(char for char in (item.phone or "") if char.isdigit()),
            )
            if key in existing:
                skipped += 1
                continue
            participant = Participant(
                list_id=participant_list.id,
                name=item.name,
                email=str(item.email) if item.email else None,
                phone=item.phone,
            )
            session.add(participant)
            existing.add(key)
            imported += 1
        return ImportCommitResponse(imported_count=imported, skipped_count=skipped)
