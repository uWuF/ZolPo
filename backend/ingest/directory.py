"""
Build registry entries for a Cerberus chain's Tel Aviv stores.

Given a chain key (e.g. "rami_levy"), this:
  1. logs in to the publishedprices portal,
  2. reads the Stores directory and keeps City == Tel Aviv,
  3. keeps only stores that actually have a downloadable PriceFull right now,
  4. downloads those PriceFull files into data/dumps/<chain>/<store>/,
  5. geocodes the addresses,
  6. returns ready-to-merge registry dicts.

This is the path you repeat to add the next Cerberus chain — see
docs/ADDING_A_CHAIN.md.
"""

from __future__ import annotations

import re
import uuid as _uuid
import xml.etree.ElementTree as ET

from app.config import CHAINS, TEL_AVIV_CITY_CODE, dump_dir, store_key
from .cerberus import (CerberusClient, download_store_pricefull,
                       fetch_stores_directory, newest_pricefull_name)
from .geocode import geocode

# Curated English labels for the known Rami Levy Tel Aviv branches; anything new
# falls back to a street-glossary transliteration of the address.
RAMI_LEVY_LABELS_EN = {
    "733": "Ben Yehuda 23",
    "734": "Esther HaMalka",
    "736": "Shocken",
    "737": "Ben Yehuda 174",
    "055": "Ramat HaChayal",
    "735": "HaChashmonaim",
}

# HE -> EN for the common Tel Aviv street names, used to auto-build label_en for
# chains with many branches (AM:PM, Yellow). First match wins; anything not in
# the glossary keeps the chain name + store id.
_STREETS_EN = {
    "בן יהודה": "Ben Yehuda", "דיזנגוף": "Dizengoff", "אלנבי": "Allenby",
    "קינג גורג": "King George", "קינג ג'ורג": "King George", "שנקין": "Sheinkin",
    "ארלוזורוב": "Arlozorov", "אבן גבירול": "Ibn Gvirol", "נורדאו": "Nordau",
    "הירקון": "HaYarkon", "בוגרשוב": "Bograshov", "ריינס": "Reines",
    "יהודה הלוי": "Yehuda HaLevi", "רוטשילד": "Rothschild", "פלורנטין": "Florentin",
    "לוינסקי": "Levinsky", "סלמה": "Salame", "דרך סלמה": "Salame", "הרצל": "Herzl",
    "יפו": "Jaffa", "דרך נמיר": "Namir Road", "יצחק שדה": "Yitzhak Sadeh",
    "החשמונאים": "HaHashmonaim", "קרליבך": "Carlebach", "אחד העם": "Ahad Ha'am",
    "בזל": "Basel", "ז'בוטינסקי": "Jabotinsky", "דרך הטייסים": "HaTayasim Road",
    "אילת": "Eilat", "המסגר": "HaMasger", "לה גוורדיה": "La Guardia",
    "אבו כביר": "Abu Kabir", "נווה צדק": "Neve Tzedek", "עולי ציון": "Olei Zion",
    "ויצמן": "Weizmann", "פנקס": "Pinkas", "דרך השלום": "Derech HaShalom",
    "משה דיין": "Moshe Dayan", "קיבוץ גלויות": "Kibbutz Galuyot",
    "לבנדה": "Levanda", "הר ציון": "Har Zion", "שלבים": "Shlavim",
    "קלישר": "Kalisher", "דניאל": "Daniel", "מח\"ל": "Machal", "לח\"י": "Lahi",
    "ה' באייר": "Kikar HaMedina", "דבורה הנביאה": "Dvora HaNevia",
    "פנחס רוזן": "Pinchas Rozen", "מאז\"ה": "Maze", "איינשטיין": "Einstein",
    "יהודה מכבי": "Yehuda Maccabi", "יגאל אלון": "Yigal Alon",
    "פרישמן": "Frishman", "שדרות ירושלים": "Jerusalem Blvd",
    "קרמינצקי": "Kremenetski", "אורי צבי גרינברג": "Uri Zvi Grinberg",
    "תלמוד בבלי": "Bavli", "הלוחמים": "Wolfson", "חרוץ": "Yad Eliyahu",
    "דרך מנחם בגין": "Menachem Begin", "נחלת יצחק": "Nachalat Yitzhak",
    "נחלת-יצחק": "Nachalat Yitzhak", "צייטלין": "Zeitlin", "גורדון": "Gordon",
    "פינסקר": "Pinsker", "לוינסקי": "Levinsky", "אחימאיר": "Achimeir",
    "ניסים אלוני": "Nisim Aloni", "שאול המלך": "Shaul HaMelech",
    "גני התערוכה": "TLV Port", "גני-התערוכה": "TLV Port", "הברזל": "HaBarzel",
}


def _label_en(chain: dict, sid: str, store_name: str, address: str) -> str:
    """Curated Rami Levy label, else street-glossary from address/name, else id."""
    if chain["key"] == "rami_levy" and sid in RAMI_LEVY_LABELS_EN:
        return RAMI_LEVY_LABELS_EN[sid]
    text = f"{address} {store_name}"
    for he, en in _STREETS_EN.items():
        if he in text:
            num = ""
            m = re.search(rf"{re.escape(he)}\s*(\d+)|(\d+)\s*{re.escape(he)}", text)
            if m:
                num = " " + (m.group(1) or m.group(2))
            return f"{en}{num}"
    return f"{chain['name_en']} {sid.lstrip('0') or sid}"


def _t(node, *names) -> str:
    for n in names:
        e = node.find(n)
        if e is not None and e.text:
            return e.text.strip()
    return ""


def parse_stores_directory(raw: bytes) -> list[dict]:
    """Flatten a Stores<chain>.xml into [{store_id, city, store_name, address, zip, subchain_id}]."""
    root = ET.fromstring(raw)
    out = []
    # Stores can be nested under SubChain nodes (carrying SubChainID) or flat.
    for sub in root.iter("SubChain"):
        sub_id = _t(sub, "SubChainID", "SubChainId")
        for st in sub.iter("Store"):
            out.append(_store_dict(st, sub_id))
    if not out:  # flat layout
        for st in root.iter("Store"):
            out.append(_store_dict(st, ""))
    return out


def _store_dict(st, sub_id: str) -> dict:
    return {
        "store_id": _t(st, "StoreID", "StoreId"),
        "city": _t(st, "City"),
        "store_name": _t(st, "StoreName"),
        "address": _t(st, "Address"),
        "zip": _t(st, "ZipCode", "ZIPCode"),
        "subchain_id": sub_id,
    }


def _is_tel_aviv(city: str) -> bool:
    """Chains write City as the numeric code (5000) or as a Hebrew name."""
    c = (city or "").strip()
    return c == TEL_AVIV_CITY_CODE or "תל אביב" in c


def _is_shoppable(store: dict) -> bool:
    """Drop fulfilment/picking centres and test venues — not walk-in stores."""
    name = store.get("store_name", "")
    return not ("ליקוט" in name or "Test Venue" in name or "CLOSED" in name)


def _build_entries(chain_key: str, directory: list[dict], has_price, download,
                   do_geocode: bool) -> list[dict]:
    """
    Portal-agnostic core: filter Tel Aviv stores that have a live PriceFull,
    download it, geocode, and emit ready-to-merge registry dicts.
    `has_price(sid) -> bool-ish`, `download(sid) -> None` are portal closures.
    """
    chain = CHAINS[chain_key]
    excluded = {sid.lstrip("0") for sid in chain.get("exclude_stores", [])}
    ta = [s for s in directory
          if _is_tel_aviv(s["city"]) and s["store_id"] and _is_shoppable(s)
          and s["store_id"].lstrip("0") not in excluded]

    entries = []
    for s in ta:
        sid = s["store_id"]
        if not has_price(sid):
            continue  # no live price file -> can't compare, skip
        download(sid)

        geo = {"lat": None, "lon": None, "geo_approx": True}
        if do_geocode:
            geo = geocode(s["address"], zip_code=s["zip"])

        entries.append({
            "uuid": str(_uuid.uuid4()),
            "key": store_key(chain["id"], sid),
            "chain": chain["name_en"],
            "chain_key": chain_key,
            "chain_int": chain["id"],
            "chain_id": chain["chain_id_gov"],
            "subchain_id": s["subchain_id"],
            "store_id": sid,
            "format": chain["name_he"],
            "format_en": chain.get("format_en", f"{chain['name_en']} (supermarket)"),
            "store_name": s["store_name"],
            "label_en": _label_en(chain, sid, s["store_name"], s["address"]),
            "label_he": s["store_name"],
            "city": "תל אביב - יפו",
            "city_code": TEL_AVIV_CITY_CODE,
            "address": s["address"].replace(",", " ").strip(),
            "zip": s["zip"],
            "lat": geo["lat"],
            "lon": geo["lon"],
            "geo_approx": geo["geo_approx"],
            "dump": f"{chain_key}/{sid}",
        })
    return entries


def build_tel_aviv_registry(chain_key: str, do_geocode: bool = True) -> list[dict]:
    """Tel Aviv registry entries for a Cerberus (publishedprices.co.il) chain."""
    chain = CHAINS[chain_key]
    client = CerberusClient(chain["cerberus_user"],
                            chain.get("cerberus_password", "")).login()
    directory = parse_stores_directory(fetch_stores_directory(client))
    price_names = client.list_files("PriceFull")
    return _build_entries(
        chain_key, directory,
        has_price=lambda sid: newest_pricefull_name(price_names, sid),
        download=lambda sid: download_store_pricefull(
            client, sid, dump_dir(chain_key, sid), names=price_names),
        do_geocode=do_geocode,
    )


def build_tel_aviv_registry_publishprice(chain_key: str, do_geocode: bool = True) -> list[dict]:
    """Tel Aviv registry entries for a PublishPrice chain (Carrefour)."""
    from . import publishprice as pp

    files = pp.list_files(days_back=2)
    directory = parse_stores_directory(pp.fetch_stores_directory(files))
    return _build_entries(
        chain_key, directory,
        has_price=lambda sid: pp.newest_pricefull_name(files, sid),
        download=lambda sid: pp.download_store_pricefull(
            files, sid, dump_dir(chain_key, sid)),
        do_geocode=do_geocode,
    )


def build_tel_aviv_registry_bina(chain_key: str, do_geocode: bool = True) -> list[dict]:
    """Tel Aviv registry entries for a Bina chain (King Store, Good Pharm …)."""
    from . import bina
    from .cerberus import newest_file_name

    prefix = CHAINS[chain_key]["bina_prefix"]
    directory = parse_stores_directory(bina.fetch_stores_directory(prefix))
    names = bina.list_files(prefix, "PriceFull")
    return _build_entries(
        chain_key, directory,
        has_price=lambda sid: newest_file_name(names, sid, "pricefull"),
        download=lambda sid: bina.download_store_file(
            prefix, sid, dump_dir(chain_key, sid), names),
        do_geocode=do_geocode,
    )


# Super-Pharm marks a few out-of-town branches with Tel Aviv's city code (e.g.
# the Givatayim mall); the address gives them away.
_NON_TA_ADDRESS = ("גבעתיים", "רמת גן", "רמת-גן", "בני ברק", "בני-ברק", "חולון",
                   "בת ים", "בת-ים", "ראשון לציון", "פתח תקו", "הרצליה")


def build_tel_aviv_registry_superpharm(chain_key: str, do_geocode: bool = True) -> list[dict]:
    """Tel Aviv registry entries for Super-Pharm (own MVC-grid portal)."""
    from . import superpharm as sp

    directory = [s for s in parse_stores_directory(sp.fetch_stores_directory())
                 if not any(city in s["address"] for city in _NON_TA_ADDRESS)]
    ta_ids = {s["store_id"] for s in directory if _is_tel_aviv(s["city"])}
    files = sp.list_files("PriceFull", ta_ids)
    return _build_entries(
        chain_key, directory,
        has_price=lambda sid: files.get(str(sid).lstrip("0")),
        download=lambda sid: sp.download_store_file(
            sid, dump_dir(chain_key, sid), files),
        do_geocode=do_geocode,
    )


def build_tel_aviv_registry_wolt(chain_key: str, do_geocode: bool = True) -> list[dict]:
    """Tel Aviv registry entries for Wolt Market (static daily HTML index)."""
    from . import wolt

    files = wolt.list_files(days_back=2)
    directory = parse_stores_directory(wolt.fetch_stores_directory(files))
    return _build_entries(
        chain_key, directory,
        has_price=lambda sid: wolt.newest_file_name(files, sid),
        download=lambda sid: wolt.download_store_file(
            files, sid, dump_dir(chain_key, sid)),
        do_geocode=do_geocode,
    )


def build_tel_aviv_registry_citymarket(chain_key: str, do_geocode: bool = True) -> list[dict]:
    """
    Tel Aviv registry entries for City Market Shops. The portal has no usable
    chain-wide Stores directory, so the listing table's branch labels are the
    directory; stub PriceFull files (a few hundred bytes) don't count as live.
    """
    from . import citymarket as cm

    rows = cm.list_rows()
    branches = cm.tel_aviv_branches(rows, min_kb=5.0)
    directory = [{"store_id": sid, "city": "תל אביב - יפו", "zip": "",
                  "subchain_id": "", **info} for sid, info in branches.items()]
    return _build_entries(
        chain_key, directory,
        has_price=lambda sid: cm.newest_row(rows, sid, "PriceFull", min_kb=5.0),
        download=lambda sid: cm.download_store_file(
            rows, sid, dump_dir(chain_key, sid), min_kb=5.0),
        do_geocode=do_geocode,
    )
