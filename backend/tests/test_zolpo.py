"""
ZolPo unit tests (stdlib unittest — no extra dependencies, fits the no-build
philosophy). Run from the repo root or backend/:

    backend/.venv312/bin/python backend/tests/test_zolpo.py -v

Covers the spots that have already bitten us once (filename timestamp parsing)
and the invariants the app depends on (universal store keys, exact barcode
lookup, and enrichment surviving a reset ingest).
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.db as db  # noqa: E402
from app.search import _parse_keys, _escape_like, search_products, get_product  # noqa: E402
from ingest.loader import publish_ts  # noqa: E402
from ingest.cerberus import _store_field, newest_pricefull_name  # noqa: E402


class PublishTs(unittest.TestCase):
    """The 13-digit gov ChainID must never be mistaken for a date (regression)."""

    def test_format_a_shufersal(self):
        self.assertEqual(
            publish_ts("PriceFull7290027600007-001-011-20260630-021229.gz"),
            "2026-06-30 02:12:29",
        )

    def test_format_b_rami_levy_trailing_12_digits(self):
        self.assertEqual(
            publish_ts("PriceFull7290058140886-733-202606300215.xml"),
            "2026-06-30 02:15:00",
        )

    def test_chain_id_alone_is_not_a_date(self):
        self.assertEqual(publish_ts("PriceFull7290058140886-733.xml"), "")


class StoreField(unittest.TestCase):
    def test_five_part_layout(self):
        self.assertEqual(_store_field("PriceFull7290027600007-001-011-20260630-021229.gz"), "011")

    def test_three_part_layout(self):
        self.assertEqual(_store_field("PriceFull7290058140886-733-202606300215.xml"), "733")

    def test_newest_picks_latest_for_store(self):
        names = [
            "PriceFull7290058140886-733-202606290215.gz",
            "PriceFull7290058140886-733-202606300215.gz",
            "PriceFull7290058140886-734-202607010215.gz",   # other store
        ]
        self.assertEqual(newest_pricefull_name(names, "733"),
                         "PriceFull7290058140886-733-202606300215.gz")


class ParseKeys(unittest.TestCase):
    def test_valid_and_malformed(self):
        self.assertEqual(
            _parse_keys(["1:11", " 2:733 ", "junk", "x:1", "", None]),
            [(1, "11"), (2, "733")],
        )

    def test_escape_like(self):
        self.assertEqual(_escape_like("50%"), "50\\%")
        self.assertEqual(_escape_like("a_b"), "a\\_b")


class DbFixture(unittest.TestCase):
    """search/meta behaviour on a real (temp) SQLite database."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._old = db.DB_PATH
        db.DB_PATH = self.path
        db.init_db()
        with db.get_db() as conn:
            db.upsert_product(conn, "7290004127329", "קוטג' 5%", "תנובה", "cheese")
            db.upsert_product(conn, "4127329", "מוצר אחר", None, "default")  # substring code
            db.upsert_price(conn, "7290004127329", 1, "11", 6.90, "2026-06-30 02:00:00")
            db.upsert_price(conn, "7290004127329", 2, "733", 5.90, "2026-06-30 02:00:00")
            conn.execute(
                "INSERT INTO product_meta (item_code, image_url, image_source) VALUES (?,?,?)",
                ("7290004127329", "https://img.example/cottage.jpg", "shufersal"),
            )

    def tearDown(self):
        db.DB_PATH = self._old
        os.unlink(self.path)

    def test_exact_product_lookup_not_like(self):
        # "4127329" is a substring of the cottage barcode; exact lookup must
        # return the short-code product, not the cottage.
        self.assertEqual(get_product("4127329")["item_name"], "מוצר אחר")
        self.assertIsNone(get_product("0000000000000"))

    def test_search_attaches_prices_by_universal_key(self):
        res = search_products("קוטג", store_keys=["1:11", "2:733"])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["prices"], {"1:11": 6.9, "2:733": 5.9})
        self.assertEqual(res[0]["image_url"], "https://img.example/cottage.jpg")

    def test_store_filter_excludes_unstocked(self):
        # Store 2:734 stocks nothing -> filtered search returns no products.
        self.assertEqual(search_products("קוטג", store_keys=["2:734"]), [])

    def test_digit_query_matches_barcode_but_text_does_not(self):
        self.assertEqual(len(search_products("7290004127329")), 1)
        # A text query must not LIKE-match into barcodes.
        self.assertEqual(search_products("xyz"), [])

    def test_meta_survives_reset_ingest(self):
        # Simulate ingest_registry(reset=True): wipe the resettable tables …
        with db.get_db() as conn:
            conn.executescript("DELETE FROM prices; DELETE FROM products; DELETE FROM stores;")
            # … and re-ingest the same product from the gov files.
            db.upsert_product(conn, "7290004127329", "קוטג' 5%", "תנובה", "cheese")
            db.upsert_price(conn, "7290004127329", 1, "11", 7.10, "2026-07-01 02:00:00")
        res = search_products("קוטג")
        self.assertEqual(res[0]["image_url"], "https://img.example/cottage.jpg")  # survived


if __name__ == "__main__":
    unittest.main(verbosity=2)
