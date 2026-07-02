"""
Promotions pipeline: PromoFull files -> promos / promo_items tables.

The gov PromoFull schema (same family across chains):

    <Promotion>
      <PromotionId>1353482</PromotionId>
      <PromotionDescription>פטרוזליה/כוסברה 3ב10</PromotionDescription>
      <PromotionEndDate>2026-12-31</PromotionEndDate>
      <MinQty>3.00</MinQty>
      <DiscountedPrice>10.00</DiscountedPrice>
      <PromotionItems><Item><ItemCode>729...</ItemCode>...</Item></PromotionItems>
    </Promotion>

We store one row per promo per store plus an item-code link table, replacing a
store's rows wholesale on every ingest (promos churn daily). The API only
serves promos whose end_date has not passed.
"""

from __future__ import annotations

import glob
import gzip
import os
import xml.etree.ElementTree as ET

from app.config import CHAINS, dump_dir
from app.db import get_db, init_db
from app import registry

from . import publishprice, shufersal
from .cerberus import CerberusClient, download_store_file


def _text(node, *names) -> str:
    for n in names:
        e = node.find(n)
        if e is not None and e.text:
            return e.text.strip()
    return ""


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def iter_promos(path: str):
    """Yield (promo_id, description, end_date, min_qty, price, [item_codes])."""
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    for p in root.iter("Promotion"):
        promo_id = _text(p, "PromotionId", "PromotionID")
        if not promo_id:
            continue
        codes = [
            _text(it, "ItemCode")
            for it in p.iter("Item")
            if _text(it, "ItemCode") and _text(it, "IsGiftItem") != "1"
        ]
        if not codes:
            continue
        yield (
            promo_id,
            _text(p, "PromotionDescription"),
            _text(p, "PromotionEndDate")[:10],
            _num(_text(p, "MinQty")),
            _num(_text(p, "DiscountedPrice")),
            codes,
        )


def newest_promofull(chain_key: str, store_id: str) -> str | None:
    folder = dump_dir(chain_key, store_id)
    files = [f for f in glob.glob(os.path.join(folder, "*"))
             if os.path.basename(f).lower().startswith("promofull")]
    return sorted(files)[-1] if files else None


def download_all() -> dict:
    """Fetch the newest PromoFull for every registry store (all portals)."""
    stores = registry.all_stores()
    by_chain: dict[str, list] = {}
    for s in stores:
        by_chain.setdefault(s["chain_key"], []).append(s)

    stats = {"ok": 0, "missing": 0}
    for ck, chain_stores in by_chain.items():
        chain = CHAINS.get(ck)
        if not chain:
            continue
        portal = chain["portal"]
        if portal == "cerberus":
            client = CerberusClient(chain["cerberus_user"],
                                    chain.get("cerberus_password", "")).login()
            names = client.list_files("PromoFull")
            for s in chain_stores:
                p = download_store_file(client, s["store_id"],
                                        dump_dir(ck, s["store_id"]), names, "PromoFull")
                stats["ok" if p else "missing"] += 1
        elif portal == "publishprice":
            files = publishprice.list_files(days_back=2)
            for s in chain_stores:
                p = publishprice.download_store_file(files, s["store_id"],
                                                     dump_dir(ck, s["store_id"]), "PromoFull")
                stats["ok" if p else "missing"] += 1
        else:  # shufersal
            for s in chain_stores:
                p = shufersal.download_store_file(s["store_id"],
                                                  dump_dir(ck, s["store_id"]), "PromoFull")
                stats["ok" if p else "missing"] += 1
        print(f"  {ck}: promos downloaded", flush=True)
    return stats


def ingest_promos() -> dict:
    """Load the newest downloaded PromoFull of every store into the DB."""
    init_db()
    loaded = skipped = rows = 0
    with get_db() as conn:
        for s in registry.all_stores():
            ck, sid = s["chain_key"], s["store_id"]
            chain = CHAINS.get(ck, {})
            chain_int = s.get("chain_int") or chain.get("id")
            path = newest_promofull(ck, sid)
            if not path or chain_int is None:
                skipped += 1
                continue
            conn.execute("DELETE FROM promos WHERE chain_id=? AND store_id=?", (chain_int, sid))
            conn.execute("DELETE FROM promo_items WHERE chain_id=? AND store_id=?", (chain_int, sid))
            for promo_id, desc, end, qty, price, codes in iter_promos(path):
                conn.execute(
                    "INSERT OR REPLACE INTO promos VALUES (?,?,?,?,?,?,?)",
                    (chain_int, sid, promo_id, desc, end, qty, price),
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO promo_items VALUES (?,?,?,?)",
                    [(chain_int, sid, promo_id, c) for c in codes],
                )
                rows += 1
            loaded += 1
    return {"stores_loaded": loaded, "stores_skipped": skipped, "promos": rows}
