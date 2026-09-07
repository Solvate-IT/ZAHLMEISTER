from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.api.deps import get_organization
from app.db.session import SessionLocal
from app.models.entities import Organization, Participant, ParticipantList
from app.schemas.imports import ImportCommitRequest, ImportCommitResponse, ImportPreview
from app.services.imports import ImportParseError, parse_import
from app.services.plans import FREE_PARTICIPANTS_PER_LIST, participant_capacity_available

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

        candidates: list[tuple[object, tuple[str, str, str]]] = []
        seen = set(existing)
        skipped = 0
        for item in payload.participants:
            key = (
                item.name.casefold(),
                (str(item.email) if item.email else "").casefold(),
                "".join(char for char in (item.phone or "") if char.isdigit()),
            )
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            candidates.append((item, key))

        if not await participant_capacity_available(
            session,
            organization.id,
            participant_list.id,
            adding=len(candidates),
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Free plan supports up to {FREE_PARTICIPANTS_PER_LIST} participants per list",
            )

        for item, _ in candidates:
            session.add(
                Participant(
                    list_id=participant_list.id,
                    name=item.name,
                    email=str(item.email) if item.email else None,
                    phone=item.phone,
                )
            )
        return ImportCommitResponse(imported_count=len(candidates), skipped_count=skipped)
