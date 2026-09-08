from __future__ import annotations

import asyncio
from getpass import getpass

from app.core.config import settings
from app.services.auth import normalize_email
from app.services.platform_admin import set_platform_admin_password


async def main() -> None:
    configured = normalize_email(settings.platform_admin_bootstrap_email)
    allowed = sorted(settings.platform_admin_emails)
    if not allowed:
        raise SystemExit("PLATFORM_ADMIN_EMAILS is empty. Configure an allowed admin email first.")

    default_email = configured if configured in settings.platform_admin_emails else allowed[0]
    entered = input(f"Platform admin email [{default_email}]: ").strip()
    email = normalize_email(entered or default_email)
    if email not in settings.platform_admin_emails:
        raise SystemExit("The selected email is not listed in PLATFORM_ADMIN_EMAILS.")

    password = getpass("New platform admin password (minimum 16 characters): ")
    if len(password) < 16:
        raise SystemExit("Password must be at least 16 characters.")
    confirmation = getpass("Repeat password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")

    await set_platform_admin_password(email, password)
    print(f"Platform admin credentials updated for {email}.")
    print("All existing sessions for this admin account were invalidated.")


if __name__ == "__main__":
    asyncio.run(main())
