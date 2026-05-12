#!/usr/bin/env bash
# Tear down the GCE resources created by provision.sh.

set -euo pipefail

VM_NAME="${VM_NAME:-brainos-vm}"
ZONE="${ZONE:-us-central1-a}"
FIREWALL_RULE="${FIREWALL_RULE:-brainos-web}"

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
echo "▶ Project:   ${PROJECT}"
echo "▶ Will delete VM:           ${VM_NAME} (${ZONE})"
echo "▶ Will delete firewall:     ${FIREWALL_RULE}"
echo ""
echo "This permanently destroys all data on the VM's boot disk."
read -r -p "Type the VM name to confirm: " ans
if [[ "${ans}" != "${VM_NAME}" ]]; then
  echo "Aborted."
  exit 0
fi

if gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --quiet >/dev/null 2>&1; then
  echo "▶ Deleting VM..."
  gcloud compute instances delete "${VM_NAME}" --zone="${ZONE}" --quiet
else
  echo "▶ VM ${VM_NAME} not found — skipping."
fi

if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --quiet >/dev/null 2>&1; then
  echo "▶ Deleting firewall rule..."
  gcloud compute firewall-rules delete "${FIREWALL_RULE}" --quiet
else
  echo "▶ Firewall rule ${FIREWALL_RULE} not found — skipping."
fi

echo "✓ Teardown complete."
