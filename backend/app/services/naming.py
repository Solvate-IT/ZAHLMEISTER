from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Collection, Organization, ParticipantList
from app.services.locks import transaction_lock

DEFAULT_NAMES: dict[str, tuple[str, str]] = {
    "bg": ("Контакти", "Събиране"),
    "hr": ("Kontakti", "Prikupljanje"),
    "cs": ("Kontakty", "Sbírka"),
    "da": ("Kontakter", "Indsamling"),
    "nl": ("Contacten", "Inzameling"),
    "en": ("Contacts", "Collection"),
    "et": ("Kontaktid", "Kogumine"),
    "fi": ("Yhteystiedot", "Keräys"),
    "fr": ("Contacts", "Collecte"),
    "de": ("Kontakte", "Sammelaktion"),
    "el": ("Επαφές", "Συλλογή"),
    "hu": ("Kapcsolatok", "Gyűjtés"),
    "ga": ("Teagmhálaithe", "Bailiúchán"),
    "it": ("Contatti", "Raccolta"),
    "lv": ("Kontakti", "Iekasēšana"),
    "lt": ("Kontaktai", "Rinkimas"),
    "mt": ("Kuntatti", "Ġbir"),
    "pl": ("Kontakty", "Zbiórka"),
    "pt": ("Contactos", "Cobrança"),
    "ro": ("Contacte", "Colectare"),
    "sk": ("Kontakty", "Zbierka"),
    "sl": ("Stiki", "Zbiranje"),
    "es": ("Contactos", "Recaudación"),
    "sv": ("Kontakter", "Insamling"),
}


def language_code(locale: str | None) -> str:
    if not locale:
        return "en"
    return locale.replace("_", "-").split("-", maxsplit=1)[0].lower()


def default_participant_list_name(locale: str | None) -> str:
    return DEFAULT_NAMES.get(language_code(locale), DEFAULT_NAMES["en"])[0]


def default_collection_name(locale: str | None) -> str:
    return DEFAULT_NAMES.get(language_code(locale), DEFAULT_NAMES["en"])[1]


def next_available_name(base: str, existing_names: Iterable[str]) -> str:
    clean_base = " ".join(base.split()).strip()
    if not clean_base:
        raise ValueError("Name base must not be empty")

    occupied = {name.casefold() for name in existing_names}
    if clean_base.casefold() not in occupied:
        return clean_base

    number = 2
    while f"{clean_base} {number}".casefold() in occupied:
        number += 1
    return f"{clean_base} {number}"


async def unique_participant_list_name(
    session: AsyncSession,
    organization: Organization,
    requested_name: str | None,
    *,
    exclude_id: object | None = None,
) -> str:
    await transaction_lock(session, "participant-list-name", organization.id)
    base = (requested_name or "").strip() or default_participant_list_name(organization.locale)
    stmt = select(ParticipantList.name).where(
        ParticipantList.organization_id == organization.id,
        func.lower(ParticipantList.name).startswith(base.lower(), autoescape=True),
    )
    if exclude_id is not None:
        stmt = stmt.where(ParticipantList.id != exclude_id)
    names = (await session.execute(stmt)).scalars().all()
    return next_available_name(base, names)


async def unique_collection_name(
    session: AsyncSession,
    organization: Organization,
    requested_name: str | None,
    *,
    exclude_id: object | None = None,
) -> str:
    await transaction_lock(session, "collection-name", organization.id)
    base = (requested_name or "").strip() or default_collection_name(organization.locale)
    stmt = select(Collection.name).where(
        Collection.organization_id == organization.id,
        func.lower(Collection.name).startswith(base.lower(), autoescape=True),
    )
    if exclude_id is not None:
        stmt = stmt.where(Collection.id != exclude_id)
    names = (await session.execute(stmt)).scalars().all()
    return next_available_name(base, names)
