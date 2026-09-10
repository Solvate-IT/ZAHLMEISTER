#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/env.sh"

echo "Internal Zahlmeister secrets are initialized automatically."
echo "Environment: $ENVIRONMENT"
echo "Location: $INTERNAL_SECRETS_DIR"
echo "Existing values are preserved; this command does not rotate or print secrets."
