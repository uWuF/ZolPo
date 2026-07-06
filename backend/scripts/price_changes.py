"""
Random sample of price changes recorded on the latest price_history day.

    python scripts/price_changes.py               # 15 random changes
    python scripts/price_changes.py --sample 30   # more

A "change" is a delta row on the newest snapshot day that has an *earlier*
row with a different price for the same (item, store) — brand-new items
(first-ever observation, e.g. the baseline day) are not changes and are
skipped. Prints one line per change: name · store · old → new (±%).
Used by the twice-daily scheduled refresh to show a живой срез of the market.
"""

import _bootstrap  # noqa: F401
import sys

from app.db import get_db
from app.config import CHAIN_BY_ID


def sample_changes(limit: int = 15) -> tuple[str, list[dict]]:
    """Return (latest_day, [{name, chain, store, old, new}, …] random sample)."""
    with get_db() as conn:
        latest = conn.execute("SELECT MAX(day) AS d FROM price_history").fetchone()["d"]
        if latest is None:
            return "", []
        rows = conn.execute(
            """
            WITH changed AS (
                SELECT h.item_code, h.chain_id, h.store_id, h.price AS new_price,
                       (SELECT h2.price FROM price_history h2
                        WHERE h2.item_code = h.item_code AND h2.chain_id = h.chain_id
                          AND h2.store_id = h.store_id AND h2.day < h.day
                        ORDER BY h2.day DESC LIMIT 1) AS old_price
                FROM price_history h
                WHERE h.day = ?
            )
            SELECT c.item_code, c.chain_id, c.store_id, c.old_price, c.new_price,
                   p.item_name, m.item_name_en, s.store_name
            FROM changed c
            JOIN products p ON p.item_code = c.item_code
            LEFT JOIN product_meta m ON m.item_code = c.item_code
            LEFT JOIN stores s ON s.chain_id = c.chain_id AND s.store_id = c.store_id
            WHERE c.old_price IS NOT NULL AND c.old_price <> c.new_price
            ORDER BY RANDOM() LIMIT ?
            """,
            (latest, limit),
        ).fetchall()
        total = conn.execute(
            """
            SELECT COUNT(*) AS n FROM price_history h
            WHERE h.day = ? AND EXISTS (
                SELECT 1 FROM price_history h2
                WHERE h2.item_code = h.item_code AND h2.chain_id = h.chain_id
                  AND h2.store_id = h.store_id AND h2.day < h.day
                  AND h2.price <> h.price)
            """,
            (latest,),
        ).fetchone()["n"]
    return latest, rows, total


if __name__ == "__main__":
    limit = 15
    if "--sample" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--sample") + 1])
    latest, rows, total = sample_changes(limit)
    if not latest:
        print("price_history is empty — run scripts/ingest.py first.")
        sys.exit(0)
    if not rows:
        print(f"{latest}: no price changes recorded on the latest snapshot day "
              f"(baseline day, or nothing changed).")
        sys.exit(0)
    print(f"{latest}: {total} price changes; random {len(rows)}:\n")
    for r in rows:
        chain = CHAIN_BY_ID.get(r["chain_id"], {}).get("name_en", r["chain_id"])
        name = r["item_name_en"] or r["item_name"]
        pct = (r["new_price"] - r["old_price"]) / r["old_price"] * 100
        arrow = "▲" if pct > 0 else "▼"
        print(f"  {arrow} {name[:38]:<38} · {chain} {r['store_name'] or r['store_id']}"
              f" · ₪{r['old_price']:.2f} → ₪{r['new_price']:.2f} ({pct:+.0f}%)")
