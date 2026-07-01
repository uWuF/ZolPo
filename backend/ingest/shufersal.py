"""
Shufersal downloader.

Shufersal runs its own open portal (no login). The category listing returns
HTML-escaped, signed Azure blob URLs; catID 2 = PriceFull.
"""

from __future__ import annotations

import html
import os
import re

import requests

PORTAL = "https://prices.shufersal.co.il/FileObject/UpdateCategory"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) ZolPo/1.0"}


def download_store_pricefull(store_id: str, out_dir: str) -> str | None:
    """Save the newest PriceFull for one Shufersal store into out_dir."""
    r = requests.get(PORTAL, params={"catID": 2, "storeId": store_id},
                     headers=UA, timeout=40)
    links = [html.unescape(l) for l in re.findall(r'href="([^"]+)"', r.text) if "PriceFull" in l]
    if not links:
        return None
    name_of = lambda u: u.split("?")[0].split("/")[-1]
    url = sorted(links, key=name_of)[-1]          # filename sorts by timestamp -> newest
    raw = requests.get(url, headers=UA, timeout=120).content
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name_of(url).replace(".gz", ""))
    with open(path, "wb") as f:
        f.write(raw)
    return path
