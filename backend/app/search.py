"""
Product search + per-store price assembly.

The frontend sends the *universal store keys* it wants to compare
(e.g. "1:11,2:733" = Shufersal store 11 + Rami Levy store 733). We:

  1. find products matching the term (Hebrew/English name, brand, or barcode),
     restricted to items actually stocked in at least one selected store;
  2. attach the cheapest price per selected store — one grouped query for the
     whole result page, keyed by the same universal key so the frontend can
     line prices up with the right market column.

Product identity lives in `products` (from the gov files); the display extras
(image, English name) come from `product_meta` via a LEFT JOIN.
"""

from __future__ import annotations

import datetime as _dt

from .db import get_db

_PRODUCT_SELECT = """
    SELECT p.item_code, p.item_name, m.item_name_en, p.manufacture_name,
           m.image_url, p.category, p.is_weighted, p.unit_of_measure
    FROM products p LEFT JOIN product_meta m ON m.item_code = p.item_code
"""


def _internal_code(code: str) -> bool:
    """
    A store-internal code, not a globally-unique barcode: short PLU codes and
    embedded-price EAN-13 (prefix '2', the GS1 restricted / in-store range).
    Such a code means DIFFERENT products in different chains (chain A's "10" is
    a pear, chain B's "10" is something else), so it must never be matched
    across chains. Real EAN-8/12/13 (not starting with 2) are global and safe.
    """
    c = (code or "").strip()
    if not c.isdigit():
        return False
    return len(c) < 8 or (len(c) == 13 and c.startswith("2"))


def _parse_keys(keys: list[str] | None) -> list[tuple[int, str]]:
    """['1:11', '2:733'] -> [(1, '11'), (2, '733')]; ignores malformed entries."""
    pairs = []
    for k in keys or []:
        k = (k or "").strip()
        if ":" not in k:
            continue
        chain_s, store_id = k.split(":", 1)
        try:
            pairs.append((int(chain_s), store_id))
        except ValueError:
            continue
    return pairs


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a literal % or _ in the query matches itself."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _tuple_filter(pairs: list[tuple[int, str]]) -> tuple[str, list]:
    """Row-value tuple filter: (chain_id, store_id) IN ((?,?),(?,?), ...)"""
    if not pairs:
        return "", []
    clause = "(" + ",".join("(?,?)" for _ in pairs) + ")"
    params: list = []
    for cid, sid in pairs:
        params += [cid, sid]
    return clause, params


def _dominant_chain(store_map: dict) -> str:
    """The chain (of a 'chain:store' key map) with the most stores; ties → lowest id."""
    counts: dict[str, int] = {}
    for k in store_map:
        ch = k.split(":", 1)[0]
        counts[ch] = counts.get(ch, 0) + 1
    return sorted(counts, key=lambda ch: (-counts[ch], int(ch)))[0]


def _attach_prices(conn, rows, pairs) -> list[dict]:
    """Cheapest price + unit price + active promos per (product, store).

    For store-internal codes (see `_internal_code`) the maps are collapsed to a
    single chain, because the same code is a different product in another chain
    — cross-chain comparison there would be a false match."""
    codes = [r["item_code"] for r in rows]
    prices_by_code: dict[str, dict] = {c: {} for c in codes}
    units_by_code: dict[str, dict] = {c: {} for c in codes}
    promos_by_code: dict[str, dict] = {c: {} for c in codes}
    if codes:
        tuple_clause, tuple_params = _tuple_filter(pairs)
        placeholders = ",".join("?" * len(codes))

        store_filter = f" AND (chain_id, store_id) IN {tuple_clause}" if pairs else ""
        grouped = conn.execute(
            f"SELECT item_code, chain_id, store_id, MIN(price) AS price, "
            f"       MIN(unit_price) AS unit_price FROM prices "
            f"WHERE item_code IN ({placeholders}){store_filter} "
            f"GROUP BY item_code, chain_id, store_id",
            (*codes, *tuple_params),
        )
        for pr in grouped:
            key = f"{pr['chain_id']}:{pr['store_id']}"
            prices_by_code[pr["item_code"]][key] = round(pr["price"], 2)
            if pr["unit_price"] is not None:
                units_by_code[pr["item_code"]][key] = round(pr["unit_price"], 2)

        promo_filter = (f" AND (pi.chain_id, pi.store_id) IN {tuple_clause}" if pairs else "")
        promo_rows = conn.execute(
            f"""
            SELECT pi.item_code, pi.chain_id, pi.store_id,
                   p.description, p.min_qty, p.price, p.end_date, p.kind
            FROM promo_items pi
            JOIN promos p ON p.chain_id = pi.chain_id AND p.store_id = pi.store_id
                         AND p.promo_id = pi.promo_id
            WHERE pi.item_code IN ({placeholders}){promo_filter}
              AND (p.end_date IS NULL OR p.end_date = '' OR p.end_date >= date('now'))
            ORDER BY p.price IS NULL, p.price, p.end_date
            """,
            (*codes, *tuple_params),
        )
        # ALL active promos per (product, store), best (cheapest) first — a
        # product can carry several deals in one store and different deals in
        # different stores; the frontend renders the full list in a panel.
        for pr in promo_rows:
            key = f"{pr['chain_id']}:{pr['store_id']}"
            promos_by_code[pr["item_code"]].setdefault(key, []).append(
                {"text": pr["description"], "qty": pr["min_qty"],
                 "price": pr["price"], "end": pr["end_date"], "kind": pr["kind"]})

        # Phase-0: a store-internal code is a different product per chain — keep
        # only its dominant chain's stores so nothing is compared across chains.
        for code in codes:
            pmap = prices_by_code[code]
            if not _internal_code(code) or len({k.split(":", 1)[0] for k in pmap}) <= 1:
                continue
            ch = _dominant_chain(pmap)
            keep = lambda m: {k: v for k, v in m.items() if k.split(":", 1)[0] == ch}
            prices_by_code[code] = keep(pmap)
            units_by_code[code] = keep(units_by_code[code])
            promos_by_code[code] = keep(promos_by_code[code])

    def _get(r, col):
        return r[col] if col in r.keys() else None

    return [
        {
            "item_code": r["item_code"],
            "item_name": r["item_name"],
            "item_name_en": r["item_name_en"],
            "manufacture_name": r["manufacture_name"],
            "image_url": r["image_url"],
            "category": r["category"],
            "is_weighted": _get(r, "is_weighted"),
            "unit_of_measure": _get(r, "unit_of_measure"),
            "internal_code": _internal_code(r["item_code"]),
            "prices": prices_by_code[r["item_code"]],
            "unit_prices": units_by_code[r["item_code"]],
            "promos": promos_by_code[r["item_code"]],
        }
        for r in rows
    ]


PROMO_KINDS = {"one_plus_one", "x_for_y", "percent_off", "fixed_price", "club", "other"}

# guess_category() outputs — the categories the browse chips may filter on.
CATEGORIES = {"snack", "drink", "fruit", "vegetable", "milk", "cheese", "egg",
              "bread", "cleaning", "hygiene", "coffee", "meat", "chicken",
              "fish", "pasta", "rice", "water", "oil", "alcohol", "frozen",
              "sweet", "baby", "pet", "canned", "baking", "deli"}

# Landing tiles, Wolt-Market style: tile key -> fine categories it aggregates.
# The frontend renders these in this order; labels live in i18n.
TILES = {
    "produce":  ["fruit", "vegetable"],
    "dairy":    ["milk", "cheese", "egg"],
    "meat":     ["meat", "chicken", "fish"],
    "bakery":   ["bread"],
    "drinks":   ["drink", "water", "coffee"],
    "alcohol":  ["alcohol"],
    "snacks":   ["snack", "sweet"],
    "frozen":   ["frozen"],
    "pantry":   ["pasta", "rice", "oil", "canned", "baking", "deli"],
    "home":     ["cleaning"],
    "care":     ["hygiene"],
    "babypet":  ["baby", "pet"],
}


# Hand-picked tile "hero" products — iconic, recognisable pack shots from our
# own image table (cherry tomatoes, Strauss cottage, Bamba, Coca-Cola…). The
# auto-pick fallback (most-covered product with a photo) surfaces whatever the
# keyword heuristic put in the bucket, which can be off-brand for a tile cover.
_TILE_HERO = {
    "produce": ["7290012086113"],                    # cherry tomatoes on the vine
    "dairy":   ["7290011194246"],                    # Strauss cottage 5%
    "meat":    ["7290003287055", "7290109581538"],   # pargit skewers / pastrama
    "bakery":  ["7290018500361"],                    # sliced bread loaf
    "drinks":  ["7290011017866"],                    # Coca-Cola can
    "alcohol": ["7501064191527"],                    # Corona 6-pack
    "snacks":  ["7290100687109"],                    # Bamba nougat
    "frozen":  ["7290112499929"],                    # Magnum chocolate
    "pantry":  ["8076809512268"],                    # Barilla girandole
    "home":    ["8001841625188"],                    # Fairy Platinum
    "care":    ["7290112492449", "8700216527941"],   # Pinuk / Pantene shampoo
    "babypet": ["7290013083678"],                    # Materna formula
}


def category_tiles(store_keys: list[str] | None = None) -> list[dict]:
    """
    Landing category tiles: per tile, how many distinct products the selected
    stores stock and a representative photo — a Wolt-style browse grid without
    shipping any static category art. Photo = the curated hero product when we
    have its image, else the most cross-store-covered product with an image.
    """
    pairs = _parse_keys(store_keys)
    tuple_clause, tuple_params = _tuple_filter(pairs)
    scope = f"WHERE (pr.chain_id, pr.store_id) IN {tuple_clause}" if pairs else ""
    out = []
    with get_db() as conn:
        counts = {r["category"]: r["c"] for r in conn.execute(
            f"""SELECT p.category, COUNT(DISTINCT p.item_code) AS c
                FROM prices pr JOIN products p ON p.item_code = pr.item_code
                {scope} GROUP BY p.category""", tuple_params)}
        for key, cats in TILES.items():
            image = None
            for code in _TILE_HERO.get(key, []):
                row = conn.execute(
                    "SELECT image_url FROM product_meta "
                    "WHERE item_code = ? AND image_url IS NOT NULL", (code,)).fetchone()
                if row:
                    image = row["image_url"]
                    break
            if image is None:
                cat_ph = ",".join("?" * len(cats))
                row = conn.execute(
                    f"""SELECT m.image_url
                        FROM prices pr
                        JOIN products p ON p.item_code = pr.item_code
                        JOIN product_meta m ON m.item_code = p.item_code
                        {scope + ' AND' if scope else 'WHERE'} p.category IN ({cat_ph})
                          AND m.image_url IS NOT NULL
                        GROUP BY p.item_code ORDER BY COUNT(*) DESC LIMIT 1""",
                    (*tuple_params, *cats)).fetchone()
                image = row["image_url"] if row else None
            out.append({
                "key": key,
                "cats": ",".join(cats),
                "count": sum(counts.get(c, 0) for c in cats),
                "image": image,
            })
    return out


def search_products(term: str, limit: int = 60, store_keys: list[str] | None = None,
                    deals_only: bool = False, deal_kind: str = "",
                    categories: str = "") -> list[dict]:
    term = (term or "").strip()
    deal_kind = deal_kind if deal_kind in PROMO_KINDS else ""
    cats = [c for c in (categories or "").split(",") if c in CATEGORIES]
    pairs = _parse_keys(store_keys)
    tuple_clause, tuple_params = _tuple_filter(pairs)

    where = []
    params: list = []
    if cats:
        where.append(f"p.category IN ({','.join('?' * len(cats))})")
        params += cats
    if term:
        like = f"%{_escape_like(term)}%"
        conds = [
            "p.item_name LIKE ? ESCAPE '\\'",
            "m.item_name_en LIKE ? ESCAPE '\\'",
            "p.manufacture_name LIKE ? ESCAPE '\\'",
        ]
        params += [like, like, like]
        if term.isdigit():  # only an all-digit query can be a (partial) barcode
            conds.append("p.item_code LIKE ?")
            params.append(like)
        where.append("(" + " OR ".join(conds) + ")")
    if pairs:
        where.append(
            "EXISTS (SELECT 1 FROM prices pr WHERE pr.item_code = p.item_code "
            f"AND (pr.chain_id, pr.store_id) IN {tuple_clause})"
        )
        params += tuple_params
    if deals_only:
        promo_scope = f" AND (pi.chain_id, pi.store_id) IN {tuple_clause}" if pairs else ""
        kind_cond = " AND pm.kind = ?" if deal_kind else ""
        where.append(
            "EXISTS (SELECT 1 FROM promo_items pi "
            "JOIN promos pm ON pm.chain_id = pi.chain_id AND pm.store_id = pi.store_id "
            "AND pm.promo_id = pi.promo_id "
            f"WHERE pi.item_code = p.item_code{promo_scope} "
            f"AND (pm.end_date IS NULL OR pm.end_date = '' OR pm.end_date >= date('now')){kind_cond})"
        )
        if pairs:
            params += tuple_params
        if deal_kind:
            params.append(deal_kind)

    if not term and pairs:
        # No search term = the browse/landing feed. Alphabetical order surfaces
        # junk ("12ביצים…"); instead rank by how many of the selected stores
        # carry the item (the whole point is comparing), then prefer items
        # with a real photo.
        extra = [w for w in where
                 if not w.startswith("EXISTS (SELECT 1 FROM prices")]
        extra_sql = (" AND " + " AND ".join(extra)) if extra else ""
        # `params` was built in `where` order: [cats…, prices-tuple…, deals…];
        # drop the prices-tuple params since the JOIN replaces that EXISTS.
        n_cats = len(cats)
        params = params[:n_cats] + params[n_cats + len(tuple_params):]
        sql = f"""
            SELECT p.item_code, p.item_name, m.item_name_en, p.manufacture_name,
                   m.image_url, p.category, p.is_weighted, p.unit_of_measure
            FROM prices pr
            JOIN products p ON p.item_code = pr.item_code
            LEFT JOIN product_meta m ON m.item_code = p.item_code
            WHERE (pr.chain_id, pr.store_id) IN {tuple_clause}{extra_sql}
            GROUP BY p.item_code
            ORDER BY COUNT(*) DESC, (m.image_url IS NOT NULL) DESC, p.item_name
            LIMIT ?
        """
        with get_db() as conn:
            rows = conn.execute(sql, (*tuple_params, *params, limit)).fetchall()
            return _attach_prices(conn, rows, pairs)

    sql = _PRODUCT_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.item_name LIMIT ?"

    with get_db() as conn:
        rows = conn.execute(sql, (*params, limit)).fetchall()
        return _attach_prices(conn, rows, pairs)


def deals_feed(store_keys: list[str] | None = None, deal_kind: str = "",
               limit: int = 60) -> list[dict]:
    """
    The "deals radar": products ranked by how deep the discount is, within the
    selected stores. Only priced promos count (fixed_price / x_for_y), because
    a percentage needs a number to rank on. Savings = 1 - promo_unit / regular,
    measured against the shelf price *in the same store as the promo* — a promo
    in a store that never lists a shelf price for the item is treated as the item
    not being stocked there (see the frontend `carries()` rule), so it never
    becomes a phantom deal. promo_unit spreads a bundle's DiscountedPrice over its
    MinQty. Implausible values (<5% or >90%, usually bad source data) are dropped.
    """
    deal_kind = deal_kind if deal_kind in PROMO_KINDS else ""
    pairs = _parse_keys(store_keys)
    if not pairs:
        return []
    tuple_clause, tuple_params = _tuple_filter(pairs)
    kind_cond = " AND pm.kind = ?" if deal_kind else ""

    # "מעל <sum>" = a "spend over ₪X" threshold loss-leader, never a real per-unit
    # price; excluded here to match the same guard on the product cards.
    rank_sql = f"""
        WITH store_price AS (
            SELECT item_code, chain_id, store_id, MIN(price) AS reg
            FROM prices
            WHERE (chain_id, store_id) IN {tuple_clause}
            GROUP BY item_code, chain_id, store_id
        )
        SELECT pi.item_code AS code,
               MAX( (sp.reg * max(coalesce(pm.min_qty, 1), 1) - pm.price)
                    / (sp.reg * max(coalesce(pm.min_qty, 1), 1)) ) AS save_pct
        FROM promos pm
        JOIN promo_items pi
          ON pi.chain_id = pm.chain_id AND pi.store_id = pm.store_id
         AND pi.promo_id = pm.promo_id
        JOIN store_price sp
          ON sp.item_code = pi.item_code
         AND sp.chain_id = pm.chain_id AND sp.store_id = pm.store_id
        WHERE (pm.chain_id, pm.store_id) IN {tuple_clause}
          AND (pm.end_date IS NULL OR pm.end_date = '' OR pm.end_date >= date('now'))
          AND pm.price IS NOT NULL AND pm.price > 0 AND sp.reg > 0
          AND pm.description NOT LIKE '%מעל%'
          {kind_cond}
        GROUP BY pi.item_code
        HAVING save_pct > 0.05 AND save_pct < 0.9
        ORDER BY save_pct DESC
        LIMIT ?
    """
    params: list = [*tuple_params, *tuple_params]
    if deal_kind:
        params.append(deal_kind)
    params.append(limit * 3)  # headroom for the near-duplicate dedupe below

    with get_db() as conn:
        ranked = conn.execute(rank_sql, params).fetchall()
        if not ranked:
            return []
        pct = {r["code"]: r["save_pct"] for r in ranked}
        # Diversify: near-duplicate SKUs (three canola oils in a row) make the
        # radar look spammy. Keep the best-saving item per name prefix.
        names = conn.execute(
            f"SELECT item_code, item_name FROM products "
            f"WHERE item_code IN ({','.join('?' * len(pct))})", tuple(pct)).fetchall()
        name_of = {r["item_code"]: r["item_name"] or "" for r in names}
        seen_prefix: set = set()
        kept = {}
        for code in sorted(pct, key=pct.get, reverse=True):
            prefix = " ".join(name_of.get(code, "").split()[:2])
            if prefix in seen_prefix:
                continue
            seen_prefix.add(prefix)
            kept[code] = pct[code]
            if len(kept) >= limit:
                break
        pct = kept
        placeholders = ",".join("?" * len(pct))
        rows = conn.execute(
            _PRODUCT_SELECT + f" WHERE p.item_code IN ({placeholders})",
            tuple(pct.keys()),
        ).fetchall()
        products = _attach_prices(conn, rows, pairs)
        for prod in products:
            prod["save_pct"] = round(pct.get(prod["item_code"], 0.0), 3)
        products.sort(key=lambda x: x["save_pct"], reverse=True)
        return products


def get_product(item_code: str) -> dict | None:
    """Exact barcode lookup (all stores) — used by GET /api/product/{code}."""
    with get_db() as conn:
        row = conn.execute(_PRODUCT_SELECT + " WHERE p.item_code = ?", (item_code,)).fetchone()
        if row is None:
            return None
        return _attach_prices(conn, [row], [])[0]


def store_highlights(store_key: str, limit: int = 3) -> dict:
    """
    Map-pin payload for ONE store: its best real deals and its biggest recent
    price drops. Both are measured against that store's own shelf price (never
    another store's), matching the app-wide "carries" rule.

      promos – money-promos (fixed_price / x_for_y) whose per-unit price beats
               the shelf price by 5–90%, deepest first, one per barcode.
      drops  – items whose latest archived price is below the previously
               recorded one (from price_history), deepest % drop first.
    """
    pairs = _parse_keys([store_key])
    if not pairs:
        return {"promos": [], "drops": []}
    chain_id, store_id = pairs[0]

    def unit(price, qty):
        return price / max(qty or 1, 1)

    with get_db() as conn:
        promo_rows = conn.execute(
            """
            SELECT pi.item_code, p.item_name, m.item_name_en, m.image_url, p.category,
                   pr.price AS shelf, pm.price AS promo_price, pm.min_qty, pm.description
            FROM promos pm
            JOIN promo_items pi ON pi.chain_id = pm.chain_id AND pi.store_id = pm.store_id
                                AND pi.promo_id = pm.promo_id
            JOIN prices pr ON pr.item_code = pi.item_code
                           AND pr.chain_id = pm.chain_id AND pr.store_id = pm.store_id
            JOIN products p ON p.item_code = pi.item_code
            LEFT JOIN product_meta m ON m.item_code = pi.item_code
            WHERE pm.chain_id = ? AND pm.store_id = ?
              AND (pm.end_date IS NULL OR pm.end_date = '' OR pm.end_date >= date('now'))
              AND pm.price IS NOT NULL AND pm.price > 0 AND pr.price > 0
              AND pm.description NOT LIKE '%מעל%'
            ORDER BY (pr.price * max(coalesce(pm.min_qty, 1), 1) - pm.price)
                     / (pr.price * max(coalesce(pm.min_qty, 1), 1)) DESC
            """,
            (chain_id, store_id),
        ).fetchall()
        promos, seen = [], set()
        for r in promo_rows:
            if r["item_code"] in seen:
                continue
            u = unit(r["promo_price"], r["min_qty"])
            save = 1 - u / r["shelf"]
            if not (0.05 < save < 0.9):
                continue
            seen.add(r["item_code"])
            promos.append({
                "item_code": r["item_code"], "item_name": r["item_name"],
                "item_name_en": r["item_name_en"], "image_url": r["image_url"],
                "category": r["category"], "was": round(r["shelf"], 2),
                "now": round(u, 2), "save_pct": round(save, 3),
                "text": r["description"], "qty": r["min_qty"]})
            if len(promos) >= limit:
                break

        drop_rows = conn.execute(
            """
            WITH ranked AS (
                SELECT item_code, day, price,
                       ROW_NUMBER() OVER (PARTITION BY item_code ORDER BY day DESC) AS rn,
                       LEAD(price)  OVER (PARTITION BY item_code ORDER BY day DESC) AS prev_price
                FROM price_history
                WHERE chain_id = ? AND store_id = ?
            )
            SELECT r.item_code, r.price AS now, r.prev_price AS was,
                   p.item_name, m.item_name_en, m.image_url, p.category
            FROM ranked r
            JOIN products p ON p.item_code = r.item_code
            LEFT JOIN product_meta m ON m.item_code = r.item_code
            WHERE r.rn = 1 AND r.prev_price IS NOT NULL
              AND r.price > 0 AND r.prev_price > r.price
            ORDER BY (r.prev_price - r.price) / r.prev_price DESC
            LIMIT ?
            """,
            (chain_id, store_id, limit),
        ).fetchall()
        drops = [{
            "item_code": r["item_code"], "item_name": r["item_name"],
            "item_name_en": r["item_name_en"], "image_url": r["image_url"],
            "category": r["category"], "was": round(r["was"], 2), "now": round(r["now"], 2),
            "save_pct": round(1 - r["now"] / r["was"], 3)} for r in drop_rows]

    return {"promos": promos, "drops": drops}


def price_history(item_code: str, store_keys: list[str] | None = None,
                  days: int = 90) -> list[dict]:
    """
    Per-store price series for one barcode from the append-only archive.
    History rows are delta-compressed (a row = the day the price changed), so
    each series also carries the last change *before* the window as its
    baseline — otherwise a stable price would produce an empty graph.
    Returns [{key, points: [{day, price}, …]}, …], points oldest-first.
    """
    pairs = _parse_keys(store_keys)
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    tuple_clause, tuple_params = _tuple_filter(pairs)
    store_filter = f" AND (chain_id, store_id) IN {tuple_clause}" if pairs else ""
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT chain_id, store_id, day, price FROM price_history
                WHERE item_code = ?{store_filter}
                ORDER BY chain_id, store_id, day""",
            (item_code, *tuple_params)).fetchall()
    series: dict[str, dict] = {}
    for r in rows:
        key = f"{r['chain_id']}:{r['store_id']}"
        s = series.setdefault(key, {"key": key, "baseline": None, "points": []})
        if r["day"] < cutoff:
            s["baseline"] = {"day": r["day"], "price": r["price"]}  # newest pre-window change
        else:
            s["points"].append({"day": r["day"], "price": r["price"]})
    out = []
    for s in series.values():
        pts = ([s["baseline"]] if s["baseline"] else []) + s["points"]
        if pts:
            out.append({"key": s["key"], "points": pts})
    return out
