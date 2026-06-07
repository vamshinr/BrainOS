#!/usr/bin/env bash
# Stop the whole BrainOS stack: frontend, Mnemosyne backend, Qdrant, Neo4j.
# (Data on disk is preserved — start.sh brings everything back with state intact.)
set -uo pipefail

kill_port() {
  local p="$1" name="$2" pids
  pids="$(lsof -ti tcp:"$p" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "   stopping $name (:$p) [${pids//$'\n'/ }]"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
  else
    echo "   $name not running"
  fi
}

echo "==> Frontend (3000)";          kill_port 3000 frontend
echo "==> Mnemosyne backend (8090)"; kill_port 8090 mnemosyne
echo "==> Qdrant (6333)";            kill_port 6333 qdrant

echo "==> Neo4j (7687)"
if command -v neo4j >/dev/null 2>&1 && neo4j stop >/dev/null 2>&1; then
  echo "   stopped"
else
  kill_port 7687 neo4j
fi

echo ""
echo "all servers stopped."
