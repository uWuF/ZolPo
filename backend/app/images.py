"""
Image engine. Government XML files carry no product images, so we source them
from the chains' own public storefronts, keyed by barcode:

  1. Shufersal storefront product API (P_<barcode>) -> Cloudinary shot (~63%).
  2. Rami Levy image CDN (/product/<barcode>/small.jpg)              (~24%).
  3. Open Food Facts during enrichment (see enrich.py)              (~1%).
  4. An inline category SVG placeholder for the rest.

Real URLs can only be confirmed over the network, so `scripts/resolve_images.py`
probes 1+2 for every barcode and writes the first working one into
product_meta.image_url (+ image_source) — a table that survives re-ingest.
With both chains and cross-fallback this covers ~64% of the catalog; the
frontend swaps in the SVG placeholder whenever image_url is empty or the URL
404s (<img onerror>).
"""

from __future__ import annotations

RAMI_LEVY_IMG_CDN = "https://img.rami-levy.co.il"
SHUFERSAL_PRODUCT_API = "https://www.shufersal.co.il/online/he/products"


def rami_levy_image_url(item_code: str, size: str = "small") -> str:
    """Rami Levy hosts product shots by barcode on its image CDN (may 404)."""
    return f"{RAMI_LEVY_IMG_CDN}/product/{item_code}/{size}.jpg"


def shufersal_product_api_url(item_code: str) -> str:
    """
    Shufersal storefront product endpoint. Newer SKUs use the barcode as their
    product code (P_<barcode>); the JSON response carries the Cloudinary image
    URL. Returns the API URL to query, not the image itself.
    """
    return f"{SHUFERSAL_PRODUCT_API}/P_{item_code}"


# --------------------------------------------------------------------------- #
# Category placeholders
# --------------------------------------------------------------------------- #

_PLACEHOLDER_ICONS = {
    "milk": ("🥛", "#e0f2fe"),
    "bread": ("🍞", "#fef3c7"),
    "cheese": ("🧀", "#fef9c3"),
    "egg": ("🥚", "#fff7ed"),
    "water": ("💧", "#e0f7fa"),
    "oil": ("🫒", "#ecfccb"),
    "fruit": ("🍎", "#fee2e2"),
    "vegetable": ("🥦", "#dcfce7"),
    "meat": ("🥩", "#fce7e7"),
    "chicken": ("🍗", "#fef3c7"),
    "fish": ("🐟", "#e0f2fe"),
    "snack": ("🍪", "#fef3c7"),
    "drink": ("🥤", "#ede9fe"),
    "coffee": ("☕", "#f5ebe0"),
    "rice": ("🍚", "#f8fafc"),
    "pasta": ("🍝", "#fef3c7"),
    "hygiene": ("🧴", "#fae8ff"),
    "cleaning": ("🧽", "#e0f2fe"),
    "alcohol": ("🍺", "#fef3c7"),
    "frozen": ("🧊", "#e0f2fe"),
    "sweet": ("🍫", "#fde8e8"),
    "baby": ("🍼", "#fdf2f8"),
    "pet": ("🐾", "#f5f5f4"),
    "canned": ("🥫", "#fee2e2"),
    "baking": ("🧁", "#fef9c3"),
    "deli": ("🥗", "#ecfccb"),
    "default": ("🛒", "#f1f5f9"),
}

# Hebrew keyword -> category, Wolt-Market-style granularity. First match wins,
# so specific segments (baby, pet, alcohol, frozen) come before generic food
# words. Needles are matched inside " "+name+" ", so a needle with a leading /
# trailing space anchors to a word boundary (" יין" won't match "מעיין").
_CATEGORY_KEYWORDS = {
    "baby": ["תינוק", "חיתול", "מטרנה", "סימילאק", "דייסת", "בייבי"],
    "pet": ["כלב", "חתול", "לחיות מחמד", "בונזו", "פריסקיז", "חיות מחמד"],
    "alcohol": ["בירה", " יין", "וודקה", "ויסקי", "ערק ", "ליקר", "קוניאק",
                " רום ", "ג'ין ", "שמפניה", "קאווה", "לאגר", "סיידר", "בקרדי",
                "סמירנוף", "קמפרי", "בריזר"],
    "frozen": ["קפוא", "שלגון", "גלידה", "גלידת", "מוקפא"],
    "coffee": ["קפה", " תה ", "אספרסו", "נסקפה"],
    "water": ["מים ", "סודה"],
    "drink": ["קולה", "משקה", "מיץ ", "שתיה", "ספרייט", "פאנטה", "אנרגיה",
              "טרופית", "פיוז", "ויטמינצ"],
    "milk": [" חלב", "יוגורט", "יוג.", "יופלה", "מולר", "דנונה", "שמנת",
             "חמאה", "מעדן", " שוקו ", "אקטימל", "מילקי"],
    "cheese": ["גבינה", "גבינת", "קוטג", "מוצרלה", " פטה ", "צהובה", "בולגרית",
               "קשקבל", "עמק ", "גאודה"],
    "egg": ["ביצים", "ביצי "],
    "bread": ["לחם", "פיתות", "פיתה", "חלה ", "לחמני", "בגט", "קרואסון", "מאפה"],
    "chicken": ["עוף", "פרגית", "הודו", "שניצל"],
    "meat": ["בשר", "בקר ", "טחון", "נקניק", "קבב", "המבורגר", "כבש",
             "אנטריקוט", "סטייק", "צלעות"],
    "fish": [" דג ", "דגים", "טונה", "סלמון", "הרינג", "סרדינים", "פילה ",
             "אמנון", "מושט"],
    # sweets/snacks BEFORE produce: flavour words ("ביסלי בצל", "בריזר אבטיח",
    # "סוכריות תות") would otherwise land processed goods in fruit & veg.
    "sweet": ["שוקולד", "ממתק", "סוכריות", "מסטיק", " גומי", "חלווה", "חלבה",
              "ופל", "וופל", "עוגי", "ביסקוויט", "מאפין", "עוגה", "קינדר"],
    "snack": ["במבה", "ביסלי", "חטיף", "צ'יפס", "תפוציפס", "פופקורן", "קרקר",
              "בייגלה", "גרעיני", "פיצוחים", "אגוזי", "שקדים", "בוטנים",
              "טורטיה"],
    "fruit": ["תפוח", "בננה", "תות", "ענבים", "אבטיח", "אגס", "מנגו", "אפרסק",
              "שזיף", "נקטרינה", "קלמנטינה", "תפוז", "לימון", "אבוקדו", "מלון ",
              "פירות"],
    "vegetable": ["עגבני", "מלפפון", "ירק", "בצל", "גזר", "פלפל", "חסה", "כרוב",
                  "תפוד", "קישוא", "חציל", "פטריות", "תירס", "ברוקולי", "צנונית",
                  "סלרי"],
    "canned": ["שימורי", "משומר", "זיתים", "חמוצים", "כבוש", "רסק ", "קטשופ",
               "מיונז", "חרדל "],
    "baking": ["קמח", "סוכר ", "שמרים", "אבקת אפיה", "אבקת סוכר", "וניל ",
               "קקאו", "ג'לטין"],
    "pasta": ["פסטה", "ספגטי", " פנה ", "מקרוני", "אטריות", "נודלס", "פתיתים",
              "קוסקוס"],
    "rice": ["אורז", "קינואה", "בורגול", "עדשים", "שעועית", "אפונה", "קטניות",
             "גריסים", "חומוס גרגירי"],
    "oil": ["שמן", "חומץ"],
    "deli": ["סלט ", "חומוס", "טחינה", "מטבוחה", "פסטרמה", "סלמי"],
    "hygiene": ["שמפו", "סבון", "דאודורנט", "משחת", "מברשת", "מגבונים",
                "תחליב", "קרם ", "גילוח", "טמפונים", "תחבושות", "מרכך שיער"],
    "cleaning": ["ניקוי", "אקונומיקה", "מרכך כביסה", "כביסה", "מטהר", "טואלט",
                 "נייר סופג", "מגבת נייר", "חד פעמי", "שקיות אשפה"],
}


def guess_category(item_name: str) -> str:
    """Map a Hebrew product name to a category keyword (Wolt-style buckets)."""
    hay = " " + (item_name or "") + " "
    for keyword, needles in _CATEGORY_KEYWORDS.items():
        if any(n in hay for n in needles):
            return keyword
    return "default"


def placeholder_svg(keyword: str) -> str:
    """Return an inline SVG card for a product category keyword."""
    glyph, bg = _PLACEHOLDER_ICONS.get((keyword or "").lower(), _PLACEHOLDER_ICONS["default"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" '
        f'viewBox="0 0 240 240">'
        f'<rect width="240" height="240" rx="20" fill="{bg}"/>'
        f'<text x="120" y="120" font-size="96" text-anchor="middle" '
        f'dominant-baseline="central">{glyph}</text></svg>'
    )
