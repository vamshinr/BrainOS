#!/usr/bin/env bash
# Swap the nginx cert.
#   ./init-tls.sh self-signed                              — regenerate self-signed
#   ./init-tls.sh letsencrypt example.com you@example.com  — issue Let's Encrypt cert
#
# Run from the repo root on the VM. Requires `docker compose` to be up.

set -euo pipefail

MODE="${1:-}"
CERT_DIR="${CERT_DIR:-./certs}"

usage() {
  cat <<EOF
Usage:
  $0 self-signed                              regenerate the self-signed pair
  $0 letsencrypt <domain> <email>             issue a real cert (needs domain → VM)
EOF
  exit 1
}

[[ -z "${MODE}" ]] && usage

case "${MODE}" in
  self-signed)
    echo "▶ Regenerating self-signed cert in ${CERT_DIR}..."
    mkdir -p "${CERT_DIR}"
    docker run --rm \
      -v "$(pwd)/${CERT_DIR#./}":/certs \
      alpine sh -c "
        apk add --no-cache openssl >/dev/null &&
        openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
          -keyout /certs/privkey.pem \
          -out    /certs/fullchain.pem \
          -subj '/CN=brainos.local' &&
        chmod 600 /certs/privkey.pem
      "
    docker compose restart nginx
    echo "✓ Self-signed cert installed. Browser will warn — that's expected."
    ;;

  letsencrypt)
    DOMAIN="${2:?domain required (example.com)}"
    EMAIL="${3:?email required (you@example.com)}"

    echo "▶ Pre-flight: confirm ${DOMAIN} resolves to this VM..."
    VM_IP="$(curl -fsSL -4 ifconfig.me || true)"
    DOMAIN_IP="$(getent hosts "${DOMAIN}" 2>/dev/null | awk '{print $1}' | head -1 || true)"
    if [[ -n "${VM_IP}" && -n "${DOMAIN_IP}" && "${VM_IP}" != "${DOMAIN_IP}" ]]; then
      echo "✗ ${DOMAIN} resolves to ${DOMAIN_IP}, but this VM is ${VM_IP}." >&2
      echo "  Update the DNS A record first, wait for propagation, then re-run." >&2
      exit 1
    fi

    echo "▶ Stopping nginx so certbot can bind :80..."
    docker compose stop nginx

    echo "▶ Running certbot standalone for ${DOMAIN}..."
    docker run --rm \
      -p 80:80 \
      -v "$(pwd)/letsencrypt":/etc/letsencrypt \
      certbot/certbot certonly --standalone \
        -d "${DOMAIN}" \
        --email "${EMAIL}" \
        --agree-tos \
        --no-eff-email \
        --non-interactive

    echo "▶ Copying issued cert into ${CERT_DIR}..."
    mkdir -p "${CERT_DIR}"
    cp "letsencrypt/live/${DOMAIN}/fullchain.pem" "${CERT_DIR}/fullchain.pem"
    cp "letsencrypt/live/${DOMAIN}/privkey.pem"   "${CERT_DIR}/privkey.pem"
    chmod 600 "${CERT_DIR}/privkey.pem"

    echo "▶ Starting nginx..."
    docker compose start nginx

    cat <<EOF

✓ Let's Encrypt cert installed for ${DOMAIN}.

  Open: https://${DOMAIN}

Renewal: certs expire every 90 days. Add this to root's crontab:
  0 3 * * 0  cd $(pwd) && ./deploy/gcp/init-tls.sh letsencrypt ${DOMAIN} ${EMAIL} >>/var/log/brainos-tls.log 2>&1
EOF
    ;;

  *)
    usage
    ;;
esac
