#!/usr/bin/env bash
set -euo pipefail
DOCKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IMAGE_TAG="${IMAGE_TAG:-ci-runtime}"

"$DOCKER_DIR/predeploy.sh"

case "${1:-all}" in
  all)
    "$DOCKER_DIR/scripts/security-scan.sh"
    ;;
  predeploy)
    ;;
  security)
    "$DOCKER_DIR/scripts/security-scan.sh"
    ;;
  *)
    echo "Usage: $0 [all|predeploy|security]" >&2
    exit 2
    ;;
esac
