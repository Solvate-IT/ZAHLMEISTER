import re
import subprocess
from decimal import Decimal
from urllib.parse import urlencode

_IBAN_RE = re.compile(r"^[A-Z]{2}[0-9A-Z]{13,32}$")
_BIC_RE = re.compile(r"^[A-Z0-9]{8}([A-Z0-9]{3})?$")


def normalize_iban(value: str) -> str:
    return "".join(value.upper().split())


def normalize_bic(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = "".join(value.upper().split())
    return normalized or None


def is_valid_iban(value: str) -> bool:
    iban = normalize_iban(value)
    if not _IBAN_RE.fullmatch(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(char) - 55) if char.isalpha() else char for char in rearranged)
    return int(numeric) % 97 == 1


def is_valid_bic(value: str | None) -> bool:
    bic = normalize_bic(value)
    return bic is None or bool(_BIC_RE.fullmatch(bic))


def epc_qr_payload(
    *,
    account_name: str,
    iban: str,
    bic: str | None,
    amount: Decimal,
    currency: str,
    reference: str,
) -> str | None:
    """Return EPC069-12 SCT QR payload when the payment is SEPA/EUR compatible."""
    normalized_iban = normalize_iban(iban)
    normalized_bic = normalize_bic(bic)
    if currency.upper() != "EUR" or not is_valid_iban(normalized_iban):
        return None
    if normalized_bic and not is_valid_bic(normalized_bic):
        return None

    clean_name = " ".join(account_name.split()).strip()[:70]
    clean_reference = " ".join(reference.split()).strip()[:140]
    if not clean_name or amount <= 0:
        return None

    # BCD / version / encoding / SCT / BIC / beneficiary / IBAN / amount /
    # purpose / structured reference / unstructured remittance / information.
    fields = [
        "BCD",
        "002",
        "1",
        "SCT",
        normalized_bic or "",
        clean_name,
        normalized_iban,
        f"EUR{amount:.2f}",
        "",
        "",
        clean_reference,
        "",
    ]
    return "\n".join(fields)


def public_payment_url(public_app_url: str, token: str) -> str:
    base = public_app_url.rstrip("/")
    return f"{base}/?{urlencode({'pay': token})}"


def public_payment_qr_url(public_app_url: str, token: str) -> str:
    base = public_app_url.rstrip("/")
    return f"{base}/api/v1/public/payments/{token}/qr.png"


def render_qr_png(payload: str) -> bytes:
    try:
        result = subprocess.run(
            ["qrencode", "-t", "PNG", "-o", "-", "-s", "8", "-m", "2", payload],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise OSError("QR renderer unavailable") from exc
    return result.stdout
