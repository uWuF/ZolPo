# Deploying ZolPo to a server

Everything the app needs on a fresh **Ubuntu 24.04** box, captured from the
first production deploy (DigitalOcean, 2026-07). The same playbook works on
any provider (Kamatera, Hetzner, …).

**Israeli IP matters:** Carrefour's portal (`prices.carrefour.co.il`) times
out for non-Israeli IPs and Super-Pharm's answers HTTP 492 — from a European
datacenter those two chains cannot be refreshed. Every other portal works
from anywhere. Prefer an Israeli datacenter if those chains matter.

## Bring up a new server

From the dev machine (repo root), with SSH key access as root:

```bash
IP=1.2.3.4

# 1. Code (excludes venvs, dumps and both databases)
rsync -az --exclude '.venv*' --exclude '__pycache__' \
      --exclude 'backend/data/dumps' --exclude 'backend/data/zolpo.db' \
      --exclude 'backend/data/users.db*' --exclude '.claude' --exclude '.DS_Store' \
      ./ root@$IP:/opt/zolpo/app/

# 2. Catalog DB (contains the irreplaceable price_history — always seed it
#    from the freshest copy, never start empty)
gzip -c backend/data/zolpo.db | ssh root@$IP 'gunzip -c > /opt/zolpo/app/backend/data/zolpo.db'

# 3. Bootstrap (idempotent; re-run any time). Domain optional.
ssh root@$IP 'bash /opt/zolpo/app/deploy/setup-server.sh'          # HTTP on the IP
ssh root@$IP 'bash /opt/zolpo/app/deploy/setup-server.sh zolpo.app' # or: domain + HTTPS
```

What the bootstrap sets up: Asia/Jerusalem timezone, Caddy reverse proxy,
`zolpo` system user, venv + deps, systemd unit (`zolpo.service`, port 8020
behind Caddy), cron refresh at 08:00/20:00 + nightly 03:30 backups
(14-day retention in /opt/zolpo/backups), ufw (22/80/443), WAL journal mode,
and the Sectigo intermediate cert that Linux needs for publishedprices.co.il.

## Migrating between servers

Same as above, plus copy the *live* databases from the old server (stop the
old cron first so nothing writes mid-copy) and `users.db*` sidecars if any.
`price_history` can never be re-downloaded — it only exists in zolpo.db.

## Updating code on a running server

```bash
rsync -az --exclude '.venv*' --exclude '__pycache__' --exclude 'backend/data' \
      ./ root@$IP:/opt/zolpo/app/
ssh root@$IP 'systemctl restart zolpo'
```

## Operations

- App logs: `journalctl -u zolpo -f`
- Refresh log: `/var/log/zolpo/refresh.log` (per-chain `FAILED` lines are
  isolated failures — the rest of the run is fine; `refresh FAILED` at the
  end means download/ingest/promos aborted)
- Manual refresh: `sudo -u zolpo /opt/zolpo/refresh.sh`
- SMTP for magic-link sign-in: add `ZOLPO_SMTP_HOST/PORT/USER/PASS/FROM`
  to `/etc/zolpo.env`, then `systemctl restart zolpo`
