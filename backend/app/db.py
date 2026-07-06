"""
SQLite schema and access helpers.

Tables:
  products      – one row per barcode (the cross-chain join key), as published
                  in the government price files. Cheap to rebuild: a reset
                  ingest clears and refills it.
  product_meta  – everything we *derive* about a barcode (verified image URL,
                  English name, enrichment status). Lives apart from `products`
                  so a reset ingest never wipes work that took network time or
                  money to produce (image resolving, future LLM translations).
  stores        – one row per (chain_id, store_id)
  prices        – one row per (item_code, chain_id, store_id): the CURRENT price
  price_history – append-only price observations over time, delta-compressed
                  (a row only when a price first appears or changes). Like
                  product_meta it SURVIVES reset ingests — it is the accumulating
                  asset behind price graphs, deal-honesty checks and alerts,
                  and it can never be rebuilt from a later download.
  promos / promo_items – current promotions per store (refreshed wholesale).

The (chain_id, store_id) composite is what lets us hold many chains in one DB
without store-id collisions.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH


@contextmanager
def get_db():
    """Yield a sqlite connection with Row access and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait for concurrent writers (e.g. resolve_images running during a manual
    # script) instead of failing immediately with "database is locked".
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the schema if it does not yet exist (+ light migrations)."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                item_code        TEXT PRIMARY KEY,   -- EAN/UPC barcode: the cross-chain join key
                item_name        TEXT NOT NULL,
                manufacture_name TEXT,
                category         TEXT                -- keyword used for the SVG placeholder
            );

            CREATE TABLE IF NOT EXISTS product_meta (
                item_code    TEXT PRIMARY KEY,
                item_name_en TEXT,               -- English name (LLM / OFF / manual)
                image_url    TEXT,               -- verified shot (scripts/resolve_images.py)
                image_source TEXT,               -- 'shufersal' / 'rami_levy' / 'off' / 'none'
                enriched     INTEGER DEFAULT 0   -- 0 = not yet looked up on OFF
            );

            CREATE TABLE IF NOT EXISTS stores (
                store_id   TEXT NOT NULL,
                chain_id   INTEGER NOT NULL,
                store_name TEXT,
                city       TEXT,
                address    TEXT,
                PRIMARY KEY (chain_id, store_id)
            );

            CREATE TABLE IF NOT EXISTS prices (
                item_code   TEXT NOT NULL,
                chain_id    INTEGER NOT NULL,
                store_id    TEXT NOT NULL,
                price       REAL NOT NULL,
                update_date TEXT NOT NULL,
                PRIMARY KEY (item_code, chain_id, store_id),
                FOREIGN KEY (item_code) REFERENCES products(item_code)
            );

            -- Promotions (PromoFull files). One row per promo per store; items
            -- link via promo_items. Refreshed wholesale per store on ingest.
            CREATE TABLE IF NOT EXISTS promos (
                chain_id    INTEGER NOT NULL,
                store_id    TEXT NOT NULL,
                promo_id    TEXT NOT NULL,
                description TEXT,
                end_date    TEXT,               -- 'YYYY-MM-DD'
                min_qty     REAL,
                price       REAL,               -- discounted total, if published
                kind        TEXT,               -- one_plus_one/x_for_y/percent_off/fixed_price/club/other
                PRIMARY KEY (chain_id, store_id, promo_id)
            );

            CREATE TABLE IF NOT EXISTS promo_items (
                chain_id  INTEGER NOT NULL,
                store_id  TEXT NOT NULL,
                promo_id  TEXT NOT NULL,
                item_code TEXT NOT NULL,
                PRIMARY KEY (chain_id, store_id, promo_id, item_code)
            );

            -- Append-only price archive. One row per (item, store, day) — the
            -- composite PK is what keeps observations from ever mixing. Delta-
            -- compressed: a day is recorded only when the price differs from
            -- the last recorded one (reconstruct any date as "the newest row
            -- at or before it"). NEVER cleared by reset ingests. WITHOUT ROWID:
            -- the PK covers the whole row, saving ~30% at archive scale.
            CREATE TABLE IF NOT EXISTS price_history (
                item_code TEXT NOT NULL,
                chain_id  INTEGER NOT NULL,
                store_id  TEXT NOT NULL,
                day       TEXT NOT NULL,   -- 'YYYY-MM-DD' observation date
                price     REAL NOT NULL,
                PRIMARY KEY (item_code, chain_id, store_id, day)
            ) WITHOUT ROWID;

            CREATE INDEX IF NOT EXISTS idx_products_name ON products(item_name);
            CREATE INDEX IF NOT EXISTS idx_prices_item   ON prices(item_code);
            CREATE INDEX IF NOT EXISTS idx_prices_store  ON prices(chain_id, store_id);
            CREATE INDEX IF NOT EXISTS idx_promo_items_item ON promo_items(item_code);
            """
        )
        _migrate_meta(conn)
        _migrate_promo_kind(conn)


def _migrate_promo_kind(conn) -> None:
    """Add promos.kind on DBs created before promo classification existed."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(promos)")}
    if cols and "kind" not in cols:
        conn.execute("ALTER TABLE promos ADD COLUMN kind TEXT")


def _migrate_meta(conn) -> None:
    """
    One-time migration for DBs created before `product_meta` existed: move the
    enrichment columns out of `products` (keeping the 'none' = already-checked
    markers that resolve_images.py --only-missing relies on), then drop them.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(products)")}
    legacy = {"item_name_en", "image_url", "image_source", "enriched"} & cols
    if not legacy:
        return
    select = ", ".join(c if c in cols else "NULL"
                       for c in ("item_name_en", "image_url", "image_source", "enriched"))
    conn.execute(
        f"""
        INSERT OR IGNORE INTO product_meta (item_code, item_name_en, image_url, image_source, enriched)
        SELECT item_code, {select} FROM products
        """
    )
    for c in legacy:
        conn.execute(f"ALTER TABLE products DROP COLUMN {c}")


def db_is_empty() -> bool:
    with get_db() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 0


# --------------------------------------------------------------------------- #
# Write helpers (used by the ingest pipeline)
# --------------------------------------------------------------------------- #

def upsert_product(conn, item_code, item_name, manufacture_name, category):
    # First non-empty value wins: chains load in registry order (Shufersal
    # first, with the best names), and a later chain's empty <ItemNm> must
    # never blank out a good name (that's how 5k products lost theirs once).
    conn.execute(
        """
        INSERT INTO products (item_code, item_name, manufacture_name, category)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(item_code) DO UPDATE SET
            item_name        = COALESCE(NULLIF(products.item_name, ''), excluded.item_name),
            manufacture_name = COALESCE(NULLIF(products.manufacture_name, ''), excluded.manufacture_name),
            category         = COALESCE(NULLIF(products.category, ''), excluded.category)
        """,
        (item_code, item_name, manufacture_name, category),
    )


def upsert_store(conn, store_id, chain_id, store_name, city, address):
    conn.execute(
        """
        INSERT INTO stores (store_id, chain_id, store_name, city, address)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chain_id, store_id) DO UPDATE SET
            store_name = excluded.store_name,
            city       = excluded.city,
            address    = excluded.address
        """,
        (store_id, chain_id, store_name, city, address),
    )


def record_price_history(conn, day: str | None = None) -> int:
    """
    Append the current `prices` snapshot to `price_history`, delta-compressed:
    a row is written only when an (item, store) price first appears or differs
    from the last recorded one. The very first run therefore records the whole
    catalog as the baseline. Idempotent within a day (PK upsert). Returns the
    number of rows written.

    Called at the end of every ingest — this is the append-only asset that
    price graphs, "is this deal real?" checks and price alerts read from, so
    it must never be wiped (reset ingests clear `prices`, not this).
    """
    day = day or _dt.date.today().isoformat()
    cur = conn.execute(
        """
        INSERT OR REPLACE INTO price_history (item_code, chain_id, store_id, day, price)
        SELECT pr.item_code, pr.chain_id, pr.store_id, ?, pr.price
        FROM prices pr
        LEFT JOIN (
            SELECT h.item_code, h.chain_id, h.store_id, h.price
            FROM price_history h
            JOIN (SELECT item_code, chain_id, store_id, MAX(day) AS day
                  FROM price_history
                  GROUP BY item_code, chain_id, store_id) m
              ON  m.item_code = h.item_code AND m.chain_id = h.chain_id
              AND m.store_id  = h.store_id  AND m.day      = h.day
        ) last
          ON  last.item_code = pr.item_code AND last.chain_id = pr.chain_id
          AND last.store_id  = pr.store_id
        WHERE last.price IS NULL OR last.price <> pr.price
        """,
        (day,),
    )
    return cur.rowcount


def upsert_price(conn, item_code, chain_id, store_id, price, update_date):
    conn.execute(
        """
        INSERT INTO prices (item_code, chain_id, store_id, price, update_date)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(item_code, chain_id, store_id) DO UPDATE SET
            price       = excluded.price,
            update_date = excluded.update_date
        """,
        (item_code, chain_id, store_id, price, update_date),
    )
