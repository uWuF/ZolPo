"""
Load downloaded PriceFull files into the database.

Works for any chain: the registry entry tells us the chain (`chain_int`,
`chain_key`) and where its raw file lives. Government PriceFull XML is a flat
list of <Item> nodes with ItemCode / ItemName / ItemPrice / ManufactureName.
"""

from __future__ import annotations

import glob
import os
import re
import xml.etree.ElementTree as ET

from app.config import CHAINS, dump_dir
from app.db import get_db, init_db, upsert_price, upsert_product, upsert_store
from app.images import guess_category
from app import registry


def _text(node, *names) -> str:
    for n in names:
        e = node.find(n)
        if e is not None and e.text:
            return e.text.strip()
    return ""


def publish_ts(filename: str) -> str:
    """
    Extract a 'YYYY-MM-DD HH:MM:SS' timestamp from a gov filename. Handles both
    Shufersal-style  ...-YYYYMMDD-HHMMSS  and Rami Levy format-B  ...-YYYYMMDDHHMM
    (trailing). We anchor on the dash / end of string so the 13-digit ChainID is
    never mistaken for a date.
    """
    base = os.path.basename(filename).split(".")[0]
    m = re.findall(r"(\d{8})-(\d{6})(?:\D|$)", base)   # format A (take the last match)
    if m:
        d, t = m[-1]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}:{t[4:6]}"
    m = re.search(r"(\d{12})$", base)                  # format B: trailing YYYYMMDDHHMM
    if m:
        dt = m.group(1)
        return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]} {dt[8:10]}:{dt[10:12]}:00"
    return ""


def newest_pricefull(chain_key: str, store_id: str) -> str | None:
    """Newest PriceFull file in a store's dump folder (handles .xml and .gz)."""
    folder = dump_dir(chain_key, store_id)
    files = [f for f in glob.glob(os.path.join(folder, "*"))
             if os.path.basename(f).lower().startswith("pricefull")]
    return sorted(files)[-1] if files else None


def iter_items(path: str):
    """Yield (item_code, item_name, manufacturer, price) for each priced item."""
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    for it in root.iter("Item"):
        code = _text(it, "ItemCode")
        price = _text(it, "ItemPrice")
        if not code or not price:
            continue
        try:
            price = float(price)
        except ValueError:
            continue
        yield code, _text(it, "ItemName"), _text(it, "ManufactureName", "ManufacturerName"), price


def ingest_registry(reset: bool = True) -> dict:
    """
    Load every store in the registry into the DB.

    With reset=True (default) the price/product/store tables are cleared first so
    the DB always reflects exactly the current registry + downloads.
    """
    init_db()
    if reset:
        with get_db() as conn:
            conn.executescript("DELETE FROM prices; DELETE FROM products; DELETE FROM stores;")

    stats = []
    with get_db() as conn:
        for store in registry.all_stores():
            chain_key = store.get("chain_key")
            chain = CHAINS.get(chain_key, {})
            chain_int = store.get("chain_int") or chain.get("id")
            sid = store["store_id"]
            if chain_int is None:
                stats.append({"key": store.get("key"), "error": "unknown chain"})
                continue

            path = newest_pricefull(chain_key, sid)
            if not path:
                stats.append({"key": store.get("key"), "error": "no PriceFull file"})
                continue

            ts = publish_ts(path)
            upsert_store(conn, sid, chain_int, store.get("store_name"),
                         store.get("city"), store.get("address"))
            count = 0
            for code, name, manuf, price in iter_items(path):
                # Images / English names live in product_meta (resolve_images.py,
                # enrich) and survive a reset — ingest only writes identity fields.
                upsert_product(conn, code, name, manuf, guess_category(name))
                upsert_price(conn, code, chain_int, sid, price, ts)
                count += 1
            stats.append({"key": store.get("key"), "label": store.get("label_en"),
                          "chain": chain_key, "products": count, "last_update": ts})

    return {"stores": stats}
