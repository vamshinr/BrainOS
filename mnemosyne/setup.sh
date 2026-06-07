#!/usr/bin/env bash
# One-command setup for the Mnemosyne causal memory engine (native / dev).
# Creates an isolated venv, installs deps, scaffolds .env, warms the embedding
# model, and checks that Neo4j + Qdrant are reachable.
#
#   ./setup.sh           # set up everything
#   ./run.sh             # then start the API (run.sh auto-runs setup if needed)
#
# For a brand-new machine with nothing installed, prefer Docker instead:
#   ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PY="${PYTHON:-python3}"
VENV="$HERE/.venv"

echo "==> Mnemosyne setup"

if [ ! -d "$VENV" ]; then
  echo "==> creating venv at $VENV"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> installing requirements (first run pulls torch — be patient)"
pip install --quiet --upgrade pip
pip install --quiet -r "$HERE/requirements.txt"

if [ ! -f "$REPO/.env" ]; then
  cp "$REPO/.env.example" "$REPO/.env"
  echo "==> created root .env from template — set NEO4J_PASSWORD and ANTHROPIC_API_KEY"
fi

echo "==> warming embedding model (all-MiniLM-L6-v2)"
python -c "from sentence_transformers import SentenceTransformer as S; S('all-MiniLM-L6-v2')" >/dev/null 2>&1 \
  || echo "   (warm skipped — model will download on first use)"

echo "==> checking services"
# Run from the repo root so 'import mnemosyne' resolves.
( cd "$REPO" && python - <<'PY'
import urllib.request
from mnemosyne.config import get_settings
s = get_settings()
try:
    urllib.request.urlopen(s.qdrant_url, timeout=3)
    print(f"   Qdrant     OK   ({s.qdrant_url})")
except Exception:
    print(f"   Qdrant     DOWN ({s.qdrant_url}) -> start Qdrant or use 'docker compose up'")
try:
    from mnemosyne.graph import Neo4jGraphStore
    g = Neo4jGraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password,
                        database=s.neo4j_database, event_label=s.neo4j_event_label)
    g.verify(); g.close()
    print(f"   Neo4j      OK   ({s.neo4j_uri})")
except Exception as e:
    print(f"   Neo4j      DOWN/AUTH ({s.neo4j_uri}) -> set NEO4J_PASSWORD in root .env [{type(e).__name__}]")
print("   Anthropic  " + ("OK   (key set)" if s.has_anthropic else "MISSING -> set ANTHROPIC_API_KEY for /ingest"))
PY
)

echo ""
echo "==> setup complete. Start the API:  ./run.sh            (native, :8090)"
echo "                              or:  ./run.sh --docker   (full stack via Docker)"
