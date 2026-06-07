#!/usr/bin/env bash
# Start the Mnemosyne API. Single entry point:
#   ./run.sh            # native: bootstraps via setup.sh on first run, then serves :8090
#   ./run.sh --docker   # full stack via the root docker-compose.yml
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

if [ "${1:-}" = "--docker" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found — install Docker Desktop, or run natively with ./run.sh"; exit 1
  fi
  cd "$REPO"
  exec docker compose up --build
fi

# Native path: bootstrap on first run so a single command works on a fresh checkout.
if [ ! -d "$HERE/.venv" ]; then
  echo "==> first run: bootstrapping via setup.sh"
  "$HERE/setup.sh"
fi
# shellcheck disable=SC1091
source "$HERE/.venv/bin/activate"
cd "$REPO"
echo "==> serving Mnemosyne on http://localhost:${PORT:-8090}  (Ctrl-C to stop)"
exec python -m mnemosyne
