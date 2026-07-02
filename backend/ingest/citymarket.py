"""
Client for the City Market Shops portal (citymarket-shops.co.il).

An umbrella portal for independent franchise mini-markets (City Market branches
plus "Matok BaShuk" shops in the Carmel market). A paginated table lists every
file with its branch label ("<company>, <street> <city>"); downloads are
per-row ``/downloadFile/<guid>`` links returning the gzip payload.

Quirks handled here:
  - two filename layouts, sometimes with a zeroed chain id
    (PriceFull7290000000003-063-<ts> / PriceFull...-000-023-<date>-<time>.gz);
  - some branches publish stub PriceFull files with a handful of items, so
    callers can require a minimum payload size;
  - there is no usable chain-wide Stores directory (each shop's Stores file
    holds just itself) — the branch labels in the table are the directory.
"""

from __future__ import annotations

import gzip
import html as _html
import io
import os
import re
import zipfile

import requests

BASE = "http://www.citymarket-shops.co.il/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}

_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_HREF = re.compile(r'href="(/downloadFile/[^"]+)"')
_PAGE = re.compile(r"p=(\d+)")

# A row: (file_name, branch_label, href, size_kb)
Row = tuple[str, str, str, float]


def _clean(cell: str) -> str:
    return _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell))).strip()


def list_rows(max_pages: int = 12) -> list[Row]:
    """All table rows across the listing pages."""
    rows: list[Row] = []
    total = 1
    for page in range(1, max_pages + 1):
        url = BASE if page == 1 else f"{BASE}?p={page}"
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        if page == 1:
            pages = [int(p) for p in _PAGE.findall(r.text)]
            total = max(pages) if pages else 1
        for row in _ROW.findall(r.text)[1:]:
            tds = [_clean(t) for t in _TD.findall(row)]
            href = _HREF.search(row)
            if len(tds) < 6 or not href:
                continue
            try:
                size = float(tds[5].replace(",", ""))
            except ValueError:
                size = 0.0
            rows.append((tds[2], tds[1], href.group(1), size))
        if page >= total:
            break
    return rows


def store_field(filename: str) -> str:
    """Store id from either layout (chain-sub-store-date-time / chain-store-ts)."""
    parts = filename.split(".")[0].split("-")
    if len(parts) >= 5:
        return parts[2]
    if len(parts) == 3:
        return parts[1]
    return ""


def newest_row(rows: list[Row], store_id: str, prefix: str = "PriceFull",
               min_kb: float = 0.0) -> Row | None:
    """Newest row for a store, ignoring stub files below `min_kb`."""
    sid = str(store_id).lstrip("0")
    cands = [r for r in rows
             if r[0].startswith(prefix)
             and store_field(r[0]).lstrip("0") == sid
             and r[3] >= min_kb]
    # Timestamp is the tail of the name in both layouts -> lexicographic works
    # only within one layout; sort by the trailing digit run instead.
    def ts(row: Row) -> str:
        m = re.search(r"(\d{8}-?\d{4,6})$", row[0].split(".")[0])
        return (m.group(1).replace("-", "") if m else "0").ljust(14, "0")
    return sorted(cands, key=ts)[-1] if cands else None


def download(href: str) -> bytes:
    raw = requests.get(BASE.rstrip("/") + href, headers=UA, timeout=120).content
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    if raw[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(raw))
        return zf.read(zf.namelist()[0])
    return raw


def download_store_file(rows: list[Row], store_id: str, out_dir: str,
                        prefix: str = "PriceFull", min_kb: float = 0.0) -> str | None:
    """Save the newest <prefix> file for `store_id`. Returns the path or None."""
    row = newest_row(rows, store_id, prefix, min_kb)
    if not row:
        return None
    name, _, href, _ = row
    os.makedirs(out_dir, exist_ok=True)
    base = name.replace(".gz", "")
    if not base.endswith(".xml"):
        base += ".xml"
    path = os.path.join(out_dir, base)
    with open(path, "wb") as f:
        f.write(download(href))
    return path


def tel_aviv_branches(rows: list[Row], min_kb: float = 5.0) -> dict[str, dict]:
    """
    {store_id: {store_name, address}} for branches whose label mentions Tel Aviv
    and that have a real (non-stub) PriceFull.
    """
    out: dict[str, dict] = {}
    for name, branch, _href, _size in rows:
        if "תל אביב" not in branch or not name.startswith("PriceFull"):
            continue
        sid = store_field(name)
        if not sid or sid.lstrip("0") in {k.lstrip("0") for k in out}:
            continue
        if not newest_row(rows, sid, "PriceFull", min_kb):
            continue  # only stub files -> nothing to compare
        # "מתוק בשוק הכרמל בע"מ, קלישר 3 תל אביב" -> name / address
        company, _, addr = branch.partition(",")
        out[sid] = {"store_name": company.strip(), "address": addr.strip()}
    return out
