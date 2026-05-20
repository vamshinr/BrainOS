#!/usr/bin/env bash
# Backwards-compatible shim. The real scripts now live under deploy/gcp/.
# See deploy/gcp/README.md for the full GCP deployment guide.

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ -x "${HERE}/deploy/gcp/bootstrap.sh" ]]; then
  exec "${HERE}/deploy/gcp/bootstrap.sh"
else
  # Running standalone (e.g. piped from curl) — fetch bootstrap from GitHub.
  exec bash <(curl -fsSL https://raw.githubusercontent.com/vamshinr/BrainOS/main/deploy/gcp/bootstrap.sh)
fi
