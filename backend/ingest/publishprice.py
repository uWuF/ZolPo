"""
Client for the "PublishPrice" portal family (prices.<chain>.co.il) — used by
Carrefour Israel (ex Yeinot Bitan / Mega, ChainID 7290055700007).

No login. The index page embeds the day's directory in inline JS:

    const path = '20260701';
    const files = [{"name": "PriceFull...gz", "size": ..., "modified": ...}, ...];

`?date=YYYYMMDD` selects the folder; files download from /<path>/<name>.
Because the "today" folder fills up gradually overnight, we merge the last two
days and keep the newest file per store.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta

import requests

from .cerberus import _store_field  # same gov filename layouts

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}
BASE = "https://prices.carrefour.co.il"


def _listing(day: str | None = None) -> tuple[str, list[str]]:
    """(folder path, [file names]) for one day's folder (default: today's)."""
    url = BASE + (f"/?date={day}" if day else "/")
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    path = re.search(r"const path = ([^;]+);", r.text).group(1).strip().strip("'\"")
    raw = json.loads(re.search(r"const files = (\[[^\n]*\])", r.text).group(1))
    names = [f if isinstance(f, str) else (f.get("name") or "") for f in raw]
    return path, [n for n in names if n]


def list_files(days_back: int = 2) -> dict[str, str]:
    """{file name -> folder path} merged over the last `days_back` days."""
    out: dict[str, str] = {}
    days = [None] + [
        (date.today() - timedelta(days=i)).strftime("%Y%m%d")
        for i in range(1, days_back)
    ]
    for day in days:
        try:
            path, names = _listing(day)
        except Exception:
            continue
        for n in names:
            out.setdefault(n, path)
    return out


def download(files: dict[str, str], name: str) -> bytes:
    raw = requests.get(f"{BASE}/{files[name]}/{name}", headers=UA, timeout=120).content
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw


def fetch_stores_directory(files: dict[str, str]) -> bytes:
    names = [n for n in files if n.lower().startswith("stores")]
    if not names:
        raise RuntimeError("no Stores directory file on portal")
    return download(files, sorted(names)[-1])


def newest_pricefull_name(files: dict[str, str], store_id: str) -> str | None:
    sid = str(store_id).lstrip("0")
    cands = [n for n in files
             if n.lower().startswith("pricefull")
             and (_store_field(n) or "").lstrip("0") == sid]
    return sorted(cands)[-1] if cands else None


def download_store_pricefull(files: dict[str, str], store_id: str, out_dir: str) -> str | None:
    name = newest_pricefull_name(files, store_id)
    if not name:
        return None
    raw = download(files, name)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name.replace(".gz", "") + ("" if name.endswith(".xml") else ".xml"))
    with open(path, "wb") as f:
        f.write(raw)
    return path
