"""
Client for the Super-Pharm price-transparency portal (prices.super-pharm.co.il).

An MVC-grid file listing, newest first, ~20 rows per page. Server-side filters
that actually work: ``Category-equals`` (Price / PriceFull / Promo / PromoFull /
Stores) and ``Date-equals`` (DD/MM/YYYY). ``Name-contains`` is silently ignored,
so per-store fetching walks the newest-first pages and stops as soon as every
wanted store has a file. Download links return the gzip payload directly.
"""

from __future__ import annotations

import gzip
import html as _html
import os
import re

import requests

BASE = "http://prices.super-pharm.co.il"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}

_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_HREF = re.compile(r'href="(/Download/[^"]+)"')
_PAGER = re.compile(r'data-page="(\d+)"')


def _rows(kind: str, page: int) -> tuple[list[tuple[str, str]], int]:
    """One listing page -> ([(file_name, href)], total_pages)."""
    params = {"Category-equals": kind}
    if page > 1:
        params["page"] = page
    r = requests.get(BASE + "/", params=params, headers=UA, timeout=60)
    r.raise_for_status()
    pages = [int(p) for p in _PAGER.findall(r.text)]
    out = []
    for row in _ROW.findall(r.text)[1:]:  # [0] is the header
        href = _HREF.search(row)
        name = re.search(r"((?:Price|Promo|Stores)[\w.-]+?\.gz)", row)
        if href and name:
            out.append((_html.unescape(name.group(1)), _html.unescape(href.group(1))))
    return out, (max(pages) if pages else 1)


def _store_field(filename: str) -> str:
    """Store id from PriceFull<chain>-<sub>-<store>-<date>-<time>.gz."""
    parts = filename.split(".")[0].split("-")
    return parts[2] if len(parts) >= 5 else ""


def list_files(kind: str = "PriceFull", store_ids: set[str] | None = None,
               max_pages: int = 40) -> dict[str, tuple[str, str]]:
    """
    Newest (file_name, href) per store id, walking newest-first pages.
    Stops early once every id in `store_ids` is covered.
    """
    want = {s.lstrip("0") for s in store_ids} if store_ids else None
    found: dict[str, tuple[str, str]] = {}
    page, total = 1, 1
    while page <= min(total, max_pages):
        rows, total = _rows(kind, page)
        if not rows:
            break
        for name, href in rows:
            sid = _store_field(name).lstrip("0")
            if sid and sid not in found:
                found[sid] = (name, href)
        if want and want <= set(found):
            break
        page += 1
    return found


def download(href: str) -> bytes:
    raw = requests.get(BASE + href, headers=UA, timeout=120).content
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def fetch_stores_directory() -> bytes:
    """Raw bytes of the newest Stores directory file."""
    rows, _ = _rows("Stores", 1)
    if not rows:
        raise RuntimeError("no Stores file on the Super-Pharm portal")
    return download(rows[0][1])


def download_store_file(store_id: str, out_dir: str,
                        files: dict[str, tuple[str, str]] | None = None,
                        kind: str = "PriceFull") -> str | None:
    """Save the newest <kind> file for `store_id`. Returns the path or None."""
    files = files if files is not None else list_files(kind, {store_id})
    hit = files.get(str(store_id).lstrip("0"))
    if not hit:
        return None
    name, href = hit
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name.replace(".gz", ".xml"))
    with open(path, "wb") as f:
        f.write(download(href))
    return path
