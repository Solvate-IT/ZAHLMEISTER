# Secrets

Only `.gitkeep` files belong in Git. Real credentials must never be committed or included in ZIP
source deliveries.

Production application secrets live in `production/` and are mounted read-only. Generate the core
files with `../scripts/generate-secrets.sh`. Optional provider certificates remain in their own
subdirectories such as `ponto/`.

External service passwords and credentials that cannot be generated locally must be provisioned
manually as files with restrictive permissions. In particular:

- `production/platform_smtp_password` is the password for the central Zahlmeister outbound mailbox.
- `production/platform_imap_password` is the password for the central Zahlmeister reply mailbox.
- `production/microsoft365_client_secret` is used only when the Microsoft 365 integration is enabled.
- `production/google_play_service_account.json` is the Google Cloud service-account credential used
  by the backend for Google Play subscription verification, acknowledgement, and authenticated RTDN
  processing. Development may use the corresponding file in `development/`.

The Google Play credential is mounted as
`/run/secrets/internal/google_play_service_account.json`. Configure the Pub/Sub push subscription to
use the same service account for OIDC authentication; the backend verifies its signed identity token.

Never reuse development credentials in production and never commit any of these files.
