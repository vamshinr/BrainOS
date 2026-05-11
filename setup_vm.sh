#!/bin/bash
# Run this once on a fresh Ubuntu 22.04 GCE VM.
# Usage: bash setup_vm.sh

set -e

echo "==> Installing Docker..."
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

echo "==> Installing Docker Compose..."
sudo curl -L "https://github.com/docker/compose/releases/download/v2.24.0/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

echo "==> Installing git..."
sudo apt-get install -y git

echo "==> Cloning BrainOS..."
git clone https://github.com/vamshinr/BrainOS.git
cd BrainOS
git checkout deploy_test

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit the backend env:  nano src/python_backend/.env"
echo "     Set CLAUDE_API_KEY, leave VLLM_API_BASE empty"
echo "  2. Start everything:      docker-compose up -d --build"
echo "  3. Check logs:            docker-compose logs -f"
echo "  4. Open in browser:       http://\$(curl -s ifconfig.me)"
