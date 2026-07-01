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
    "default": ("🛒", "#f1f5f9"),
}

# Hebrew keyword -> category. First match wins.
_CATEGORY_KEYWORDS = {
    "milk": ["חלב"],
    "cheese": ["גבינה", "קוטג"],
    "bread": ["לחם", "פיתות", "חלה"],
    "egg": ["ביצים", "ביצה"],
    "oil": ["שמן"],
    "water": ["מים"],
    "drink": ["קולה", "משקה", "מיץ", "סודה", "בירה", "יין"],
    "coffee": ["קפה", "תה"],
    "rice": ["אורז"],
    "pasta": ["פסטה", "ספגטי", "פנה", "מקרוני"],
    "chicken": ["עוף", "פרגית"],
    "meat": ["בשר", "בקר", "טחון", "נקניק"],
    "fish": ["טונה", "דג", "סלמון"],
    "fruit": ["תפוח", "בננה", "תות", "ענבים", "אבטיח", "אגס", "מנגו"],
    "vegetable": ["עגבני", "מלפפון", "ירק", "בצל", "גזר", "פלפל", "חסה"],
    "snack": ["במבה", "ביסלי", "חטיף", "עוגי", "שוקולד", "חטיפים", "ופל"],
    "hygiene": ["שמפו", "סבון", "דאודורנט", "משחת", "טואלט", "חיתול", "מגבונים"],
    "cleaning": ["ניקוי", "אקונומיקה", "מרכך", "כביסה", "מטהר"],
}


def guess_category(item_name: str) -> str:
    """Map a Hebrew product name to a placeholder category keyword."""
    name = item_name or ""
    for keyword, needles in _CATEGORY_KEYWORDS.items():
        if any(n in name for n in needles):
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
