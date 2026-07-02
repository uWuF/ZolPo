"""
Client for the Wolt Market price-transparency portal.

Wolt publishes a static daily HTML index at
``wm-gateway.wolt.com/isr-prices/public/v1/<YYYY-MM-DD>.html`` whose links are
relative ``download/<date>/<file>.gz`` paths (PriceFull / PromoFull per dark
store, one Stores file for the whole chain). Folders for "today" fill up just
after midnight, so we merge the last two days like the Carrefour portal.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import os
import re

import requests

BASE = "https://wm-gateway.wolt.com/isr-prices/public/v1/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}

_LINK = re.compile(r'href="(download/[^"]+)"')


def list_files(days_back: int = 2) -> list[str]:
    """Relative download paths from the last `days_back` daily indexes, newest day first."""
    out: list[str] = []
    today = _dt.date.today()
    for db in range(days_back):
        day = (today - _dt.timedelta(days=db)).isoformat()
        try:
            r = requests.get(f"{BASE}{day}.html", headers=UA, timeout=60)
            if r.status_code == 200:
                out.extend(_LINK.findall(r.text))
        except requests.RequestException:
            continue
    return out


def download(rel_path: str) -> bytes:
    raw = requests.get(BASE + rel_path.lstrip("/"), headers=UA, timeout=120).content
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def newest_file_name(files: list[str], store_id: str, prefix: str = "PriceFull") -> str | None:
    """Newest matching path; files are PriceFull<chain>-<sub>-<store>-<date>-<time>.gz."""
    sid = str(store_id).lstrip("0")
    cands = []
    for path in files:
        name = os.path.basename(path)
        if not name.lower().startswith(prefix.lower()):
            continue
        parts = name.split(".")[0].split("-")
        if len(parts) >= 5 and parts[2].lstrip("0") == sid:
            cands.append(path)
    return sorted(cands, key=os.path.basename)[-1] if cands else None


def fetch_stores_directory(files: list[str] | None = None) -> bytes:
    files = files if files is not None else list_files()
    stores = [p for p in files if os.path.basename(p).lower().startswith("stores")]
    if not stores:
        raise RuntimeError("no Stores file on the Wolt portal")
    return download(sorted(stores, key=os.path.basename)[-1])


def download_store_file(files: list[str], store_id: str, out_dir: str,
                        prefix: str = "PriceFull") -> str | None:
    """Save the newest <prefix> file for `store_id`. Returns the path or None."""
    path = newest_file_name(files, store_id, prefix)
    if not path:
        return None
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.basename(path).replace(".gz", ".xml"))
    with open(out, "wb") as f:
        f.write(download(path))
    return out
