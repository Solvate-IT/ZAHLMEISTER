# Secrets

Only `.gitkeep` files belong in Git. Real credentials must never be committed or included in ZIP
source deliveries.

Production application secrets live in `production/` and are mounted read-only. Generate the core
files with `../scripts/generate-secrets.sh`. Optional provider certificates remain in their own
subdirectories such as `ponto/`.
