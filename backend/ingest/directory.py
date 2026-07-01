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

import uuid as _uuid
import xml.etree.ElementTree as ET

from app.config import CHAINS, TEL_AVIV_CITY_CODE, dump_dir, store_key
from .cerberus import (CerberusClient, download_store_pricefull,
                       fetch_stores_directory, newest_pricefull_name)
from .geocode import geocode

# Curated English labels for the known Rami Levy Tel Aviv branches; anything new
# falls back to "Rami Levy <id>" until a nicer label is added.
RAMI_LEVY_LABELS_EN = {
    "733": "Ben Yehuda 23",
    "734": "Esther HaMalka",
    "736": "Shocken",
    "737": "Ben Yehuda 174",
    "055": "Ramat HaChayal",
    "735": "HaChashmonaim",
}


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


def build_tel_aviv_registry(chain_key: str, do_geocode: bool = True) -> list[dict]:
    chain = CHAINS[chain_key]
    client = CerberusClient(chain["cerberus_user"]).login()

    directory = parse_stores_directory(fetch_stores_directory(client))
    ta = [s for s in directory if s["city"] == TEL_AVIV_CITY_CODE and s["store_id"]]

    price_names = client.list_files("PriceFull")
    entries = []
    for s in ta:
        sid = s["store_id"]
        if not newest_pricefull_name(price_names, sid):
            continue  # no live price file -> can't compare, skip
        download_store_pricefull(client, sid, dump_dir(chain_key, sid), names=price_names)

        geo = {"lat": None, "lon": None, "geo_approx": True}
        if do_geocode:
            geo = geocode(s["address"], zip_code=s["zip"])

        label_en = RAMI_LEVY_LABELS_EN.get(sid, f"{chain['name_en']} {sid}")
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
            "format_en": f"{chain['name_en']} (supermarket)",
            "store_name": s["store_name"],
            "label_en": label_en,
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
