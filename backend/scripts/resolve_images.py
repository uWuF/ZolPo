"""
Resolve a real, verified product image URL for every barcode and store it in
product_meta.image_url (+ image_source) — the enrichment table that survives
re-ingest. Sources, in priority order:

  1. Shufersal storefront product API (P_<barcode>)  -> Cloudinary product shot.
  2. Rami Levy image CDN (/product/<barcode>/small.jpg).

A barcode neither chain has is left with image_url = NULL, so the frontend shows
the category SVG placeholder. With both chains + cross-fallback this resolves
~71% of the catalog.

    python scripts/resolve_images.py                 # resolve every product
    python scripts/resolve_images.py --only-missing  # skip already-resolved rows
    python scripts/resolve_images.py --limit 500     # quick sample run
"""

import _bootstrap  # noqa: F401
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.db import get_db, init_db
from app.images import rami_levy_image_url, shufersal_product_api_url

UA = "ZolPo/1.0 (richard.ya95@gmail.com)"
TIMEOUT = 12
WORKERS = 8
# Shufersal returns several renditions; prefer a card-sized one.
SHUF_FORMAT_PREF = ("product", "zoom", "thumbnail")


def _open(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def shufersal_image(item_code):
    """A Cloudinary image URL from Shufersal's product API, or None."""
    try:
        with _open(shufersal_product_api_url(item_code),
                   {"accept": "application/json"}) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read().decode())
    except Exception:
        return None
    images = data.get("images") or []
    by_format = {im.get("format"): im.get("url") for im in images if im.get("url")}
    for fmt in SHUF_FORMAT_PREF:
        if by_format.get(fmt):
            return by_format[fmt]
    for im in images:
        if im.get("url"):
            return im["url"]
    return None


def rami_levy_image(item_code):
    """The Rami Levy CDN URL if it actually serves an image, else None."""
    url = rami_levy_image_url(item_code)
    try:
        with _open(url, {"referer": "https://www.rami-levy.co.il/"}) as r:
            ok = (r.status == 200
                  and r.headers.get("Content-Type", "").startswith("image")
                  and int(r.headers.get("Content-Length", "0") or 0) > 800)
            return url if ok else None
    except Exception:
        return None


def resolve_one(item_code):
    """(item_code, url, source) — Shufersal first, then Rami Levy, then None."""
    url = shufersal_image(item_code)
    if url:
        return item_code, url, "shufersal"
    url = rami_levy_image(item_code)
    if url:
        return item_code, url, "rami_levy"
    return item_code, None, None


def main():
    argv = sys.argv[1:]
    only_missing = "--only-missing" in argv
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    init_db()  # make sure product_meta exists
    with get_db() as conn:
        query = ("SELECT p.item_code FROM products p "
                 "LEFT JOIN product_meta m ON m.item_code = p.item_code")
        if only_missing:
            query += " WHERE m.image_source IS NULL"
        if limit:
            query += f" LIMIT {int(limit)}"
        codes = [r["item_code"] for r in conn.execute(query).fetchall()]
        total = len(codes)
        print(f"Resolving images for {total:,} products "
              f"(workers={WORKERS}, only_missing={only_missing})...", flush=True)

        counts = {"shufersal": 0, "rami_levy": 0, "none": 0}
        processed = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for code, url, source in pool.map(resolve_one, codes):
                # 'none' = checked, no image found. The WHERE keeps an existing
                # image (e.g. from Open Food Facts) instead of stomping it with a miss.
                conn.execute(
                    """
                    INSERT INTO product_meta (item_code, image_url, image_source)
                    VALUES (?, ?, ?)
                    ON CONFLICT(item_code) DO UPDATE SET
                        image_url = excluded.image_url,
                        image_source = excluded.image_source
                    WHERE NOT (excluded.image_source = 'none'
                               AND product_meta.image_url IS NOT NULL)
                    """,
                    (code, url, source or "none"),
                )
                counts[source or "none"] += 1
                processed += 1
                if processed % 250 == 0:
                    conn.commit()
                    hits = counts["shufersal"] + counts["rami_levy"]
                    rate = processed / (time.time() - t0)
                    print(f"  {processed:,}/{total:,}  hits={hits:,} "
                          f"(sh={counts['shufersal']:,} rl={counts['rami_levy']:,})  "
                          f"{rate:.0f}/s", flush=True)
        conn.commit()

    hits = counts["shufersal"] + counts["rami_levy"]
    pct = (hits / total * 100) if total else 0
    print(f"\nDone. {hits:,}/{total:,} resolved ({pct:.1f}%) — "
          f"Shufersal {counts['shufersal']:,}, Rami Levy {counts['rami_levy']:,}, "
          f"none {counts['none']:,} (placeholder).", flush=True)


if __name__ == "__main__":
    main()
