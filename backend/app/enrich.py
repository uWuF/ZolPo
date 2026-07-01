"""
Open Food Facts enrichment: English product names + product images.

Government price files give us Hebrew names and barcodes only. We look each
barcode up on Open Food Facts (one request fills both name and image) and cache
the result by setting products.enriched = 1 so we never re-query it.

This is also where the "space for proper English" lives on the data side: once a
barcode has a real ``item_name_en`` (from OFF or a future manual/LLM pass), the
frontend shows it verbatim instead of the on-the-fly transliteration.
"""

from __future__ import annotations

import time

import requests

from .db import get_db

# Israel instance first (canonical for Israeli barcodes), then the world host.
OFF_HOSTS = ("https://il.openfoodfacts.org", "https://world.openfoodfacts.org")
OFF_UA = "ZolPo/1.0 (richard.ya95@gmail.com)"
OFF_FIELDS = "product_name,product_name_en,image_front_url,image_url,image_small_url"


def open_food_facts_lookup(item_code: str, timeout: float = 6.0) -> dict:
    """
    One round-trip to Open Food Facts per barcode.

    Returns {"name_en", "image_url", "status"} where status is:
      "ok"          – found (name/image may still be None)
      "miss"        – not in OFF
      "ratelimited" – HTTP 429; caller should back off and retry later
    """
    rate_limited = False
    for host in OFF_HOSTS:
        url = f"{host}/api/v2/product/{item_code}.json?fields={OFF_FIELDS}"
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": OFF_UA})
        except requests.RequestException:
            continue
        if resp.status_code == 429:
            rate_limited = True
            break
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("application/json"):
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        if data.get("status") != 1:
            continue
        p = data.get("product", {})
        name = (p.get("product_name_en") or p.get("product_name") or "").strip()
        # Reject names that are still entirely Hebrew — they add nothing in EN mode.
        if name and all("א" <= c <= "ת" or c == " " for c in name):
            name = ""
        image = p.get("image_front_url") or p.get("image_url") or p.get("image_small_url")
        return {"name_en": name or None, "image_url": image or None, "status": "ok"}
    return {"name_en": None, "image_url": None,
            "status": "ratelimited" if rate_limited else "miss"}


def enrich_batch(limit: int = 40) -> dict:
    """Enrich up to `limit` not-yet-checked products. Used by POST /api/enrich."""
    unchecked = (
        "SELECT p.item_code FROM products p "
        "LEFT JOIN product_meta m ON m.item_code = p.item_code "
        "WHERE COALESCE(m.enriched, 0) = 0"
    )
    with get_db() as conn:
        codes = [r["item_code"] for r in conn.execute(unchecked + " LIMIT ?", (limit,))]

    got_name = got_image = checked = 0
    rate_limited = False
    for code in codes:
        info = open_food_facts_lookup(code)
        if info["status"] == "ratelimited":
            rate_limited = True   # leave this + the rest unmarked for a later retry
            break
        checked += 1
        with get_db() as conn:
            # OFF only *fills gaps*: never overwrite a chain-verified image or an
            # existing English name (COALESCE keeps the old value when set).
            conn.execute(
                """
                INSERT INTO product_meta (item_code, item_name_en, image_url, image_source, enriched)
                VALUES (?, ?, ?, CASE WHEN ? IS NOT NULL THEN 'off' END, 1)
                ON CONFLICT(item_code) DO UPDATE SET
                    item_name_en = COALESCE(product_meta.item_name_en, excluded.item_name_en),
                    image_url    = COALESCE(product_meta.image_url, excluded.image_url),
                    image_source = CASE WHEN product_meta.image_url IS NULL AND excluded.image_url IS NOT NULL
                                        THEN 'off' ELSE product_meta.image_source END,
                    enriched     = 1
                """,
                (code, info["name_en"], info["image_url"], info["image_url"]),
            )
        got_name += 1 if info["name_en"] else 0
        got_image += 1 if info["image_url"] else 0
        time.sleep(0.4)  # ~150 req/min — polite to OFF, avoids 429

    with get_db() as conn:
        remaining = conn.execute(
            f"SELECT COUNT(*) AS n FROM ({unchecked})"
        ).fetchone()["n"]

    return {"checked": checked, "names": got_name, "images": got_image,
            "remaining": remaining, "rate_limited": rate_limited}
