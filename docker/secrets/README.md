# Secrets

Only `.gitkeep` files belong in Git. Real credentials must never be committed or included in ZIP
source deliveries.

Production application secrets live in `production/` and are mounted read-only. Generate the core
files with `../scripts/generate-secrets.sh`. Optional provider certificates remain in their own
subdirectories such as `ponto/`.

External service passwords that cannot be generated locally must be provisioned manually as files
with restrictive permissions. In particular:

- `production/platform_smtp_password` is the password for the central Zahlmeister outbound mailbox.
- `production/platform_imap_password` is the password for the central Zahlmeister reply mailbox.
- `production/microsoft365_client_secret` is used only when the Microsoft 365 integration is enabled.

Never reuse development credentials in production and never commit any of these files.
