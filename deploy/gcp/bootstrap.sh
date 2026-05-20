#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 22.04 GCE VM for BrainOS.
# Idempotent: safe to re-run.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/vamshinr/BrainOS.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
CLONE_DIR="${CLONE_DIR:-$HOME/BrainOS}"

echo "▶ Updating apt and installing prerequisites..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg git

if ! command -v docker >/dev/null 2>&1; then
  echo "▶ Installing Docker Engine + Compose plugin..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "  (you may need to log out and back in for the 'docker' group to apply)"
else
  echo "▶ Docker already installed — skipping."
fi

if [[ ! -d "${CLONE_DIR}/.git" ]]; then
  echo "▶ Cloning ${REPO_URL} → ${CLONE_DIR}..."
  git clone --branch "${REPO_BRANCH}" "${REPO_URL}" "${CLONE_DIR}"
else
  echo "▶ Repo already at ${CLONE_DIR} — pulling latest..."
  git -C "${CLONE_DIR}" pull --ff-only
fi

cat <<EOF

✓ Bootstrap complete.

Next steps:
  cd ${CLONE_DIR}
  cp src/python_backend/.env.example src/python_backend/.env
  nano src/python_backend/.env          # set CLAUDE_API_KEY or LLM_API_BASE
  docker compose up -d --build
  docker compose logs -f                # watch startup

Open in browser:
  http://\$(curl -s ifconfig.me)
EOF
