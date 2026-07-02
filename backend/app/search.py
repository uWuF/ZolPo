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

from .db import get_db

_PRODUCT_SELECT = """
    SELECT p.item_code, p.item_name, m.item_name_en, p.manufacture_name,
           m.image_url, p.category
    FROM products p LEFT JOIN product_meta m ON m.item_code = p.item_code
"""


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


def _attach_prices(conn, rows, pairs) -> list[dict]:
    """Two grouped queries: cheapest price + active promo per (product, store)."""
    codes = [r["item_code"] for r in rows]
    prices_by_code: dict[str, dict] = {c: {} for c in codes}
    promos_by_code: dict[str, dict] = {c: {} for c in codes}
    if codes:
        tuple_clause, tuple_params = _tuple_filter(pairs)
        placeholders = ",".join("?" * len(codes))

        store_filter = f" AND (chain_id, store_id) IN {tuple_clause}" if pairs else ""
        grouped = conn.execute(
            f"SELECT item_code, chain_id, store_id, MIN(price) AS price FROM prices "
            f"WHERE item_code IN ({placeholders}){store_filter} "
            f"GROUP BY item_code, chain_id, store_id",
            (*codes, *tuple_params),
        )
        for pr in grouped:
            key = f"{pr['chain_id']}:{pr['store_id']}"
            prices_by_code[pr["item_code"]][key] = round(pr["price"], 2)

        promo_filter = (f" AND (pi.chain_id, pi.store_id) IN {tuple_clause}" if pairs else "")
        promo_rows = conn.execute(
            f"""
            SELECT pi.item_code, pi.chain_id, pi.store_id,
                   p.description, p.min_qty, p.price, p.end_date
            FROM promo_items pi
            JOIN promos p ON p.chain_id = pi.chain_id AND p.store_id = pi.store_id
                         AND p.promo_id = pi.promo_id
            WHERE pi.item_code IN ({placeholders}){promo_filter}
              AND (p.end_date IS NULL OR p.end_date = '' OR p.end_date >= date('now'))
            ORDER BY p.price IS NULL, p.price
            """,
            (*codes, *tuple_params),
        )
        for pr in promo_rows:  # first (cheapest) promo per (product, store) wins
            key = f"{pr['chain_id']}:{pr['store_id']}"
            slot = promos_by_code[pr["item_code"]]
            if key not in slot:
                slot[key] = {"text": pr["description"], "qty": pr["min_qty"],
                             "price": pr["price"], "end": pr["end_date"]}

    return [
        {
            "item_code": r["item_code"],
            "item_name": r["item_name"],
            "item_name_en": r["item_name_en"],
            "manufacture_name": r["manufacture_name"],
            "image_url": r["image_url"],
            "category": r["category"],
            "prices": prices_by_code[r["item_code"]],
            "promos": promos_by_code[r["item_code"]],
        }
        for r in rows
    ]


def search_products(term: str, limit: int = 60, store_keys: list[str] | None = None,
                    deals_only: bool = False) -> list[dict]:
    term = (term or "").strip()
    pairs = _parse_keys(store_keys)
    tuple_clause, tuple_params = _tuple_filter(pairs)

    where = []
    params: list = []
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
        where.append(
            "EXISTS (SELECT 1 FROM promo_items pi "
            "JOIN promos pm ON pm.chain_id = pi.chain_id AND pm.store_id = pi.store_id "
            "AND pm.promo_id = pi.promo_id "
            f"WHERE pi.item_code = p.item_code{promo_scope} "
            "AND (pm.end_date IS NULL OR pm.end_date = '' OR pm.end_date >= date('now')))"
        )
        if pairs:
            params += tuple_params

    sql = _PRODUCT_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.item_name LIMIT ?"

    with get_db() as conn:
        rows = conn.execute(sql, (*params, limit)).fetchall()
        return _attach_prices(conn, rows, pairs)


def get_product(item_code: str) -> dict | None:
    """Exact barcode lookup (all stores) — used by GET /api/product/{code}."""
    with get_db() as conn:
        row = conn.execute(_PRODUCT_SELECT + " WHERE p.item_code = ?", (item_code,)).fetchone()
        if row is None:
            return None
        return _attach_prices(conn, [row], [])[0]
