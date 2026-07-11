#!/bin/bash
# ZolPo server bootstrap — idempotent; run as root on a fresh Ubuntu 24.04.
#
#   bash deploy/setup-server.sh [domain]
#
# Prereq: the repo must already sit at /opt/zolpo/app (rsync it from the dev
# machine — see deploy/README.md; zolpo.db is NOT in git and is copied
# separately). Passing a domain switches Caddy to it and turns on HTTPS +
# secure cookies; without one, the app serves plain HTTP on the IP.
set -euo pipefail
DOMAIN="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

[ -f /opt/zolpo/app/backend/requirements.txt ] || {
  echo "ERROR: repo not found at /opt/zolpo/app — rsync it there first"; exit 1; }

timedatectl set-timezone Asia/Jerusalem
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3.12-venv git ufw sqlite3 curl \
  debian-keyring debian-archive-keyring apt-transport-https >/dev/null

# Caddy (reverse proxy, automatic HTTPS once a domain exists)
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi

# publishedprices.co.il omits its TLS intermediate cert. macOS fetches missing
# intermediates by itself, Linux does not — without this, every Cerberus chain
# (Rami Levy, AM:PM, Yellow, …) fails with CERTIFICATE_VERIFY_FAILED.
cp "$SCRIPT_DIR/sectigo-dv-r36.pem" /usr/local/share/ca-certificates/sectigo-dv-r36.crt
update-ca-certificates >/dev/null

useradd -r -m -d /opt/zolpo -s /usr/sbin/nologin zolpo 2>/dev/null || true
mkdir -p /opt/zolpo/backups /var/log/zolpo

cd /opt/zolpo/app/backend
[ -d .venv312 ] || python3.12 -m venv .venv312
.venv312/bin/pip install -q -r requirements.txt

# Env file: SMTP creds and base URL live here, never in git.
if [ ! -f /etc/zolpo.env ]; then
  if [ -n "$DOMAIN" ]; then
    printf 'ZOLPO_BASE_URL=https://%s\nZOLPO_SECURE_COOKIES=1\n' "$DOMAIN" > /etc/zolpo.env
  else
    printf 'ZOLPO_BASE_URL=http://%s\n' "$(hostname -I | awk '{print $1}')" > /etc/zolpo.env
  fi
  chmod 600 /etc/zolpo.env
fi

install -m 755 "$SCRIPT_DIR/refresh.sh" /opt/zolpo/refresh.sh
install -m 755 "$SCRIPT_DIR/backup.sh"  /opt/zolpo/backup.sh
cp "$SCRIPT_DIR/zolpo.service" /etc/systemd/system/zolpo.service
cp "$SCRIPT_DIR/zolpo.cron"    /etc/cron.d/zolpo

if [ -n "$DOMAIN" ]; then
  printf '%s {\n    reverse_proxy 127.0.0.1:8020\n    encode gzip\n}\n' "$DOMAIN" > /etc/caddy/Caddyfile
else
  printf ':80 {\n    reverse_proxy 127.0.0.1:8020\n    encode gzip\n}\n' > /etc/caddy/Caddyfile
fi

# WAL: readers keep serving the old snapshot while the twice-daily ingest
# rewrites prices in one long transaction.
if [ -f data/zolpo.db ]; then
  sqlite3 data/zolpo.db "PRAGMA journal_mode=WAL;" >/dev/null
fi

chown -R zolpo:zolpo /opt/zolpo /var/log/zolpo

systemctl daemon-reload
systemctl enable --now zolpo
systemctl restart zolpo caddy

ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

sleep 2
systemctl is-active zolpo caddy
echo "smoke test:"; curl -s http://127.0.0.1:8020/api/meta | head -c 100; echo
echo "OK — ZolPo is up"
