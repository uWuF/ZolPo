#!/bin/bash
# Nightly consistent SQLite snapshots; 14-day retention.
# users.db is irreplaceable (people); zolpo.db carries price_history (the moat).
set -e
d=$(date +%F)
cd /opt/zolpo/app/backend/data
for db in zolpo users; do
  [ -f "$db.db" ] || continue
  sqlite3 "$db.db" ".backup /opt/zolpo/backups/$db-$d.db"
  gzip -f "/opt/zolpo/backups/$db-$d.db"
done
find /opt/zolpo/backups -name "*.gz" -mtime +14 -delete
