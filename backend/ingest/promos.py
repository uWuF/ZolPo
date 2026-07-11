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

import datetime as _dt
import glob
import gzip
import os
import re
import xml.etree.ElementTree as ET

from app.config import CHAINS, dump_dir
from app.db import get_db, init_db
from app import registry

from . import bina, citymarket, publishprice, shufersal, superpharm, wolt
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


_RE_PLUS = re.compile(r"\d\s*\+\s*\d")                      # 1+1, 2+1
_RE_X_FOR_Y = re.compile(r"\d+\s*(?:יח'?|יחידות)?\s*ב\s*-?\s*\d+")  # 2 ב-30, 3ב20
# A bare % is almost always a product spec, not a discount: "יוגורט 6.5%" is
# fat, "בירה 5%" is alcohol. Count a percent as a discount only in discount
# phrasing — "5% הנחה", "הנחה של 10%", "20% על", "השני ב-50%".
_RE_PCT_DISCOUNT = re.compile(
    r"\d+(?:\.\d+)?\s*%\s*(?:הנחה|הוזלה)"
    r"|הנחה\s*(?:של\s*)?\d+(?:\.\d+)?\s*%"
    r"|\d+(?:\.\d+)?\s*%\s*על"
    r"|השניי?ה?\s*ב\s*-?\s*\d+(?:\.\d+)?\s*%"
)
_RE_B_PRICE = re.compile(r"ב\s*-?\s*\d+(?:\.\d+)?")         # "שימורים ב- 17.90"
_RE_LEAD_PRICE = re.compile(r"^\s*\d+(?:\.\d+)?\s+\D")      # "23.90 יוגורט…" (price-first style)


def classify_promo(desc: str, min_qty, price, rate=None) -> str:
    """
    Bucket a promo into one of the UI-filterable kinds:
    one_plus_one / x_for_y / percent_off / fixed_price / club / other.
    Description patterns win; MinQty/DiscountedPrice/DiscountRate break ties.
    """
    d = desc or ""
    if "מועדון" in d or "לחברי" in d or "מצטרפים" in d:
        return "club"
    if _RE_PLUS.search(d) or "מתנה" in d or "חינם" in d:
        return "one_plus_one"
    if _RE_X_FOR_Y.search(d):
        return "x_for_y"
    if _RE_PCT_DISCOUNT.search(d) or "השני ב" in d or "חצי מחיר" in d:
        return "percent_off"
    if min_qty and min_qty >= 2 and price:
        return "x_for_y"
    if price or _RE_B_PRICE.search(d) or _RE_LEAD_PRICE.match(d):
        return "fixed_price"
    if "הנחה" in d or (rate and rate > 0):
        return "percent_off"
    return "other"


def _iter_items(promo):
    """Item nodes across both schema dialects: <Item> (Cerberus/Bina family)
    and <PromotionItem> (Shufersal family, Wolt, Super-Pharm)."""
    yield from promo.iter("Item")
    yield from promo.iter("PromotionItem")


def iter_promos(path: str):
    """Yield (promo_id, description, end_date, min_qty, price, [item_codes])."""
    # Real product deals run for days or weeks. Blanket perks (Cibus/coupon
    # promos with end dates in 2030+) would otherwise stamp the same amber line
    # on thousands of products, drowning the actual deals.
    horizon = (_dt.date.today() + _dt.timedelta(days=550)).isoformat()
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    for p in root.iter("Promotion"):
        promo_id = _text(p, "PromotionId", "PromotionID")
        if not promo_id:
            continue
        desc = _text(p, "PromotionDescription")
        end = _text(p, "PromotionEndDate", "PromotionEndDateTime")[:10]
        if "קופון" in desc or (end and end > horizon):
            continue
        codes = [
            _text(it, "ItemCode")
            for it in _iter_items(p)
            if _text(it, "ItemCode") and _text(it, "IsGiftItem") != "1"
        ]
        if not codes:
            continue
        min_qty = _num(_text(p, "MinQty", "MinNoOfItemOffered", "MinNoOfItemsOffered"))
        price = _num(_text(p, "DiscountedPrice"))
        rate = _num(_text(p, "DiscountRate"))
        yield (
            promo_id,
            desc,
            # PromotionEndDateTime is the Shufersal-family spelling; [:10] trims
            # the ISO datetime down to the date either way.
            end,
            min_qty,
            price,
            classify_promo(desc, min_qty, price, rate),
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

    stats = {"ok": 0, "missing": 0, "failed_chains": []}
    for ck, chain_stores in by_chain.items():
        chain = CHAINS.get(ck)
        if not chain:
            continue
        try:
            _download_chain_promos(chain, ck, chain_stores, stats)
            print(f"  {ck}: promos downloaded", flush=True)
        except Exception as e:
            # Same guard as scripts/download.py: a geo-blocked portal
            # (Super-Pharm answers 492 outside IL) must not stop the rest.
            print(f"  {ck}: promos FAILED: {type(e).__name__}: {e}", flush=True)
            stats["failed_chains"].append(ck)
    return stats


def _download_chain_promos(chain: dict, ck: str, chain_stores: list, stats: dict) -> None:
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
    elif portal == "bina":
        names = bina.list_files(chain["bina_prefix"], "PromoFull")
        for s in chain_stores:
            p = bina.download_store_file(chain["bina_prefix"], s["store_id"],
                                         dump_dir(ck, s["store_id"]), names, "PromoFull")
            stats["ok" if p else "missing"] += 1
    elif portal == "superpharm":
        files = superpharm.list_files("PromoFull", {s["store_id"] for s in chain_stores})
        for s in chain_stores:
            p = superpharm.download_store_file(s["store_id"], dump_dir(ck, s["store_id"]),
                                               files, "PromoFull")
            stats["ok" if p else "missing"] += 1
    elif portal == "wolt":
        files = wolt.list_files(days_back=2)
        for s in chain_stores:
            p = wolt.download_store_file(files, s["store_id"],
                                         dump_dir(ck, s["store_id"]), "PromoFull")
            stats["ok" if p else "missing"] += 1
    elif portal == "citymarket":
        rows = citymarket.list_rows()
        for s in chain_stores:
            p = citymarket.download_store_file(rows, s["store_id"],
                                               dump_dir(ck, s["store_id"]), "PromoFull")
            stats["ok" if p else "missing"] += 1
    else:  # shufersal
        for s in chain_stores:
            p = shufersal.download_store_file(s["store_id"],
                                              dump_dir(ck, s["store_id"]), "PromoFull")
            stats["ok" if p else "missing"] += 1


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
            for promo_id, desc, end, qty, price, kind, codes in iter_promos(path):
                conn.execute(
                    "INSERT OR REPLACE INTO promos VALUES (?,?,?,?,?,?,?,?)",
                    (chain_int, sid, promo_id, desc, end, qty, price, kind),
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO promo_items VALUES (?,?,?,?)",
                    [(chain_int, sid, promo_id, c) for c in codes],
                )
                rows += 1
            loaded += 1
    return {"stores_loaded": loaded, "stores_skipped": skipped, "promos": rows}
