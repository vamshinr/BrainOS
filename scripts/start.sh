#!/usr/bin/env bash
# Start the whole BrainOS stack: Neo4j, Qdrant, Mnemosyne backend, Next.js frontend.
# Idempotent — skips anything already listening. Backend + frontend run detached;
# logs go to .logs/. Stop everything with ./scripts/stop.sh.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
LOGS="$REPO/.logs"
mkdir -p "$LOGS"

port_up() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
wait_port() {
  local p="$1" n="${2:-60}" i
  for i in $(seq 1 "$n"); do port_up "$p" && return 0; sleep 1; done
  return 1
}

# 0) single root .env
if [ ! -f "$REPO/.env" ]; then
  cp "$REPO/.env.example" "$REPO/.env"
  echo "==> created root .env from template — set NEO4J_PASSWORD + ANTHROPIC_API_KEY, then re-run"
fi

# 1) Neo4j
echo "==> Neo4j (bolt 7687)"
if port_up 7687; then
  echo "   already running"
elif command -v neo4j >/dev/null 2>&1; then
  neo4j start >/dev/null 2>&1 || echo "   'neo4j start' failed"
else
  echo "   neo4j not installed — install it or use 'docker compose up'"
fi

# 2) Qdrant
echo "==> Qdrant (6333)"
if port_up 6333; then
  echo "   already running"
elif [ -x "$HOME/qdrant-server/qdrant" ]; then
  ( cd "$HOME/qdrant-server" && nohup ./qdrant >"$LOGS/qdrant.log" 2>&1 & )
  echo "   started (log: $LOGS/qdrant.log)"
else
  echo "   qdrant binary not found at ~/qdrant-server/qdrant"
fi

echo "==> waiting for data stores…"
wait_port 7687 90 && echo "   Neo4j ready" || echo "   Neo4j NOT ready (continuing)"
wait_port 6333 60 && echo "   Qdrant ready" || echo "   Qdrant NOT ready (continuing)"

# 3) Mnemosyne backend
echo "==> Mnemosyne backend (8090)"
if port_up 8090; then
  echo "   already running"
else
  [ -d "$REPO/mnemosyne/.venv" ] || "$REPO/mnemosyne/setup.sh"
  ( cd "$REPO" && nohup mnemosyne/.venv/bin/python -m mnemosyne >"$LOGS/mnemosyne.log" 2>&1 & )
  echo "   starting (log: $LOGS/mnemosyne.log)"
fi

# 4) Frontend
echo "==> Frontend (3000)"
if port_up 3000; then
  echo "   already running"
else
  [ -d "$REPO/node_modules" ] || { echo "   installing npm deps…"; npm install --legacy-peer-deps; }
  ( cd "$REPO" && nohup npm run dev >"$LOGS/frontend.log" 2>&1 & )
  echo "   starting (log: $LOGS/frontend.log)"
fi

wait_port 8090 90 && echo "==> backend ready" || echo "==> backend slow — tail $LOGS/mnemosyne.log"
wait_port 3000 90 && echo "==> frontend ready" || echo "==> frontend slow — tail $LOGS/frontend.log"

cat <<EOF

BrainOS is up:
  UI         http://localhost:3000
  Backend    http://localhost:8090   (/health /graph /retrieve /ingest /reset)
  Neo4j      http://localhost:7474
  Qdrant     http://localhost:6333/dashboard
  logs       $LOGS/
  stop:      ./scripts/stop.sh
EOF
