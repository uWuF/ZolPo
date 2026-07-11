#!/bin/bash
# ZolPo data refresh: newest gov price files -> reload DB -> promos.
# flock prevents overlap; every ingest ends by archiving price_history.
# One geo-blocked portal only logs a per-chain FAILED line (see download.py /
# promos.py) — the rest of the chains still refresh.
exec 9>/opt/zolpo/refresh.lock
flock -n 9 || { echo "$(date -Is) skipped: previous run still active"; exit 0; }
set -o pipefail
cd /opt/zolpo/app/backend
PY=.venv312/bin/python
echo "===== $(date -Is) refresh start ====="
if $PY scripts/download.py && $PY scripts/ingest.py && $PY scripts/promos.py; then
  echo "----- price changes sample -----"
  $PY scripts/price_changes.py || true
  echo "===== $(date -Is) refresh done ====="
else
  echo "===== $(date -Is) refresh FAILED (see traceback above) ====="
fi
