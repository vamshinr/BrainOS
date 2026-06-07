#!/usr/bin/env bash
# Start ONLY the data stores Mnemosyne needs: Neo4j (bolt 7687) + Qdrant (6333).
# Idempotent — skips anything already listening. Used as the VS Code
# `preLaunchTask` so pressing F5 to debug the backend brings the stores up first.
# It deliberately does NOT start the backend or frontend (the debugger owns the
# backend; `npm run dev` owns the frontend). Stop everything with ./scripts/stop.sh.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS="$REPO/.logs"
mkdir -p "$LOGS"

port_up() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
wait_port() {
  local p="$1" n="${2:-60}" i
  for i in $(seq 1 "$n"); do port_up "$p" && return 0; sleep 1; done
  return 1
}

# 1) Neo4j
echo "==> Neo4j (bolt 7687)"
if port_up 7687; then
  echo "   already running"
elif command -v neo4j >/dev/null 2>&1; then
  neo4j start >/dev/null 2>&1 || echo "   'neo4j start' failed — check 'neo4j console'"
else
  echo "   neo4j not installed — install it or run 'docker compose up neo4j'"
fi

# 2) Qdrant
echo "==> Qdrant (6333)"
if port_up 6333; then
  echo "   already running"
elif [ -x "$HOME/qdrant-server/qdrant" ]; then
  ( cd "$HOME/qdrant-server" && nohup ./qdrant >"$LOGS/qdrant.log" 2>&1 & )
  echo "   started (log: $LOGS/qdrant.log)"
else
  echo "   qdrant binary not found at ~/qdrant-server/qdrant — or run 'docker compose up qdrant'"
fi

# 3) Wait so the backend finds them on first request (don't block F5 forever).
echo "==> waiting for data stores…"
wait_port 7687 90 && echo "   Neo4j ready"  || echo "   Neo4j NOT ready yet (backend will report degraded until it is)"
wait_port 6333 60 && echo "   Qdrant ready" || echo "   Qdrant NOT ready yet"

# Always succeed: a slow store should not abort the debug launch.
exit 0
