"""
Open Food Facts image pass for products both chains lack (image_source='none').

Israeli (729…) barcodes are ~1% hits on OFF, so by default this only walks the
*international* barcodes (~50% hit rate: Carrefour France own-brand, imported
sweets, cosmetics …). One request per barcode against the world host, ~90/min
to stay polite. Resumable: enriched=1 rows are skipped.

    python scripts/off_images.py            # international no-image barcodes
    python scripts/off_images.py --all      # include Israeli 729… too (slow)
"""

import _bootstrap  # noqa: F401
import json
import sys
import time
import urllib.request

from app.db import get_db, init_db

UA = {"User-Agent": "ZolPo/1.0 (richard.ya95@gmail.com)"}
SLEEP = 0.65  # ~90 req/min


def lookup(item_code: str):
    """(name_en, image_url) from OFF world, or (None, None)."""
    url = (f"https://world.openfoodfacts.org/api/v2/product/{item_code}.json"
           f"?fields=product_name_en,product_name,image_front_url,image_url")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read().decode())
    except Exception:
        return None, None
    if d.get("status") != 1:
        return None, None
    p = d.get("product") or {}
    name = (p.get("product_name_en") or p.get("product_name") or "").strip() or None
    if name and any("֐" <= ch <= "׿" for ch in name):
        name = None  # Hebrew-only name adds nothing
    return name, p.get("image_front_url") or p.get("image_url")


def main():
    include_israeli = "--all" in sys.argv
    init_db()
    sql = ("SELECT p.item_code FROM products p "
           "JOIN product_meta m ON m.item_code = p.item_code "
           "WHERE m.image_source = 'none' AND COALESCE(m.enriched, 0) = 0")
    if not include_israeli:
        sql += " AND substr(p.item_code, 1, 3) != '729'"
    with get_db() as conn:
        codes = [r["item_code"] for r in conn.execute(sql)]
    print(f"OFF pass over {len(codes):,} barcodes "
          f"({'incl.' if include_israeli else 'excl.'} Israeli 729…)", flush=True)

    got_img = got_name = 0
    for i, code in enumerate(codes, 1):
        name, img = lookup(code)
        with get_db() as conn:
            conn.execute(
                """
                UPDATE product_meta SET
                    item_name_en = COALESCE(item_name_en, ?),
                    image_url    = COALESCE(image_url, ?),
                    image_source = CASE WHEN image_url IS NULL AND ? IS NOT NULL
                                        THEN 'off' ELSE image_source END,
                    enriched     = 1
                WHERE item_code = ?
                """,
                (name, img, img, code),
            )
        got_img += 1 if img else 0
        got_name += 1 if name else 0
        if i % 200 == 0:
            print(f"  {i:,}/{len(codes):,}  images={got_img:,} names={got_name:,}", flush=True)
        time.sleep(SLEEP)

    print(f"\nDone: +{got_img:,} images, +{got_name:,} EN names.", flush=True)


if __name__ == "__main__":
    main()
