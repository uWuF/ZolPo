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


class NewPortalHelpers(unittest.TestCase):
    """Filename handling for the Super-Pharm / Wolt / City Market portals."""

    def test_wolt_newest_by_store(self):
        from ingest.wolt import newest_file_name
        files = [
            "download/2026-07-01/PriceFull7290058249350-000-002-20260701-000055.gz",
            "download/2026-07-02/PriceFull7290058249350-000-002-20260702-000055.gz",
            "download/2026-07-02/PriceFull7290058249350-000-010-20260702-000012.gz",
            "download/2026-07-02/PromoFull7290058249350-000-002-20260702-000040.gz",
        ]
        self.assertEqual(
            newest_file_name(files, "002"),
            "download/2026-07-02/PriceFull7290058249350-000-002-20260702-000055.gz")
        self.assertEqual(
            newest_file_name(files, "2", "PromoFull"),
            "download/2026-07-02/PromoFull7290058249350-000-002-20260702-000040.gz")

    def test_citymarket_both_layouts_and_stub_filter(self):
        from ingest.citymarket import store_field, newest_row
        self.assertEqual(store_field("PriceFull7290000000003-063-202607021730"), "063")
        self.assertEqual(store_field("PriceFull7290000000003-000-023-20260702-001416.gz"), "023")
        self.assertEqual(store_field("PriceFull0000000000000-040-202607020046"), "040")
        rows = [
            ("PriceFull7290000000003-063-202607021730", "b", "/downloadFile/x", 0.4),
            ("PriceFull7290000000003-063-202607020830", "b", "/downloadFile/y", 900.0),
            ("PriceFull7290000000003-008-202607020813", "t", "/downloadFile/z", 1200.0),
        ]
        # the newer 17:30 file is a stub -> with a size floor the 08:30 one wins
        self.assertEqual(newest_row(rows, "063", min_kb=5.0)[2], "/downloadFile/y")
        self.assertIsNone(newest_row(rows, "099", min_kb=5.0))

    def test_superpharm_store_field(self):
        from ingest.superpharm import _store_field as sp_field
        self.assertEqual(sp_field("PriceFull7290172900007-000-253-20260701-071126.gz"), "253")
        self.assertEqual(sp_field("Stores7290172900007-000-20260702-070014.gz"), "")


class ClassifyPromo(unittest.TestCase):
    def test_kinds(self):
        from ingest.promos import classify_promo
        self.assertEqual(classify_promo("מבצע 1+1", None, None), "one_plus_one")
        self.assertEqual(classify_promo("דבש מתנה", None, None), "one_plus_one")
        self.assertEqual(classify_promo("2 ב- 30.00", 2, 30.0), "x_for_y")
        self.assertEqual(classify_promo("3ב20", None, None), "x_for_y")
        self.assertEqual(classify_promo("מוצרי טרה ב-5% הנחה", None, None), "percent_off")
        self.assertEqual(classify_promo("השני ב-50%", None, None), "percent_off")
        self.assertEqual(classify_promo("שימורים ב- 17.90", None, None), "fixed_price")
        self.assertEqual(classify_promo("גאודה", 1, 12.5), "fixed_price")
        self.assertEqual(classify_promo("לחברי מועדון בלבד", None, None), "club")
        self.assertEqual(classify_promo("פיצוי משקאות", None, None), "other")

    def test_spec_percent_is_not_a_discount(self):
        """Fat/alcohol percentages in product names must not become % promos."""
        from ingest.promos import classify_promo
        # ayran 3% fat, 500ml, fixed price 9.90 — was misclassified percent_off
        self.assertEqual(classify_promo("גד משקה איירן בסגנון בלקני  5003%מל", 1, 9.9),
                         "fixed_price")
        # Tiv-Taam style: leading price, fat % in the name, no DiscountedPrice
        self.assertEqual(classify_promo("23.90 יוגורט יווני6.5% 8י130*ג", 10, None),
                         "fixed_price")
        self.assertEqual(classify_promo("169 גבינת ברי צרפתית 32% במשקל", 10, None),
                         "fixed_price")
        # real percent discounts still classify
        self.assertEqual(classify_promo("הנחה 10% על פירות וירקות", None, None),
                         "percent_off")
        self.assertEqual(classify_promo("20% על כל היין", None, None), "percent_off")
        # club sign-up prices
        self.assertEqual(classify_promo('תחליב רחצה ב-5.90 ש"ח מצטרפים', 1, 5.9), "club")


class GuessCategory(unittest.TestCase):
    def test_wolt_style_buckets(self):
        from app.images import guess_category
        self.assertEqual(guess_category("בירה גולדסטאר פחית 500מל"), "alcohol")
        self.assertEqual(guess_category("יין אדום קברנה"), "alcohol")
        self.assertEqual(guess_category("מעיין מים מינרלים 1.5"), "water")   # not alcohol
        self.assertEqual(guess_category("שניצל עוף קפוא 700ג"), "frozen")
        self.assertEqual(guess_category("גלידה וניל 1.5 ליטר"), "frozen")
        self.assertEqual(guess_category("חיתולים מידה 4"), "baby")
        self.assertEqual(guess_category("מזון לחתול 400ג"), "pet")
        self.assertEqual(guess_category("שוקולד מריר 100ג"), "sweet")
        self.assertEqual(guess_category("קטשופ היינץ 700ג"), "canned")
        self.assertEqual(guess_category("קמח לבן 1 קג"), "baking")
        self.assertEqual(guess_category("יוגורט תות 150ג"), "milk")


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
