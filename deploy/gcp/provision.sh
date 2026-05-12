#!/usr/bin/env bash
# Provision a GCE VM for BrainOS.
# Run from your laptop, not from the VM. Requires `gcloud` authenticated.

set -euo pipefail

# ── Config — edit these if you want different defaults ───────────────────────
VM_NAME="${VM_NAME:-brainos-vm}"
ZONE="${ZONE:-us-central1-a}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-2}"
DISK_SIZE_GB="${DISK_SIZE_GB:-30}"
IMAGE_FAMILY="${IMAGE_FAMILY:-ubuntu-2204-lts}"
IMAGE_PROJECT="${IMAGE_PROJECT:-ubuntu-os-cloud}"
FIREWALL_RULE="${FIREWALL_RULE:-brainos-web}"
NETWORK="${NETWORK:-default}"
# ──────────────────────────────────────────────────────────────────────────────

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [[ -z "${PROJECT}" || "${PROJECT}" == "(unset)" ]]; then
  echo "✗ No active gcloud project. Run: gcloud config set project <PROJECT_ID>" >&2
  exit 1
fi

echo "▶ Project:      ${PROJECT}"
echo "▶ VM:           ${VM_NAME} (${MACHINE_TYPE}, ${DISK_SIZE_GB} GB, ${ZONE})"
echo "▶ Image:        ${IMAGE_FAMILY}"
echo "▶ Firewall:     ${FIREWALL_RULE} (tcp:80,443)"
echo ""
read -r -p "Provision now? [y/N] " ans
[[ "${ans}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# 1. Firewall — allow HTTP from anywhere to instances tagged http-server.
if ! gcloud compute firewall-rules describe "${FIREWALL_RULE}" --quiet >/dev/null 2>&1; then
  echo "▶ Creating firewall rule ${FIREWALL_RULE}..."
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
    --network="${NETWORK}" \
    --direction=INGRESS \
    --action=ALLOW \
    --rules=tcp:80,tcp:443 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=http-server,https-server
else
  echo "▶ Firewall rule ${FIREWALL_RULE} already exists — skipping."
fi

# 2. VM
if gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --quiet >/dev/null 2>&1; then
  echo "✗ VM ${VM_NAME} already exists in ${ZONE}. Delete it first, or set VM_NAME=." >&2
  exit 1
fi

echo "▶ Creating VM ${VM_NAME}..."
gcloud compute instances create "${VM_NAME}" \
  --zone="${ZONE}" \
  --machine-type="${MACHINE_TYPE}" \
  --image-family="${IMAGE_FAMILY}" \
  --image-project="${IMAGE_PROJECT}" \
  --boot-disk-size="${DISK_SIZE_GB}GB" \
  --boot-disk-type=pd-balanced \
  --tags=http-server,https-server

EXTERNAL_IP="$(gcloud compute instances describe "${VM_NAME}" \
  --zone="${ZONE}" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"

cat <<EOF

✓ Provisioned.

  External IP:  ${EXTERNAL_IP}
  SSH:          gcloud compute ssh ${VM_NAME} --zone=${ZONE}

Next, on the VM:
  bash <(curl -fsSL https://raw.githubusercontent.com/<your-fork>/BrainOS/main/deploy/gcp/bootstrap.sh)
  cd ~/BrainOS
  cp src/python_backend/.env.example src/python_backend/.env
  nano src/python_backend/.env
  docker compose up -d --build

Then open: http://${EXTERNAL_IP}
EOF
