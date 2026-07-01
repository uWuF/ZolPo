"""
Central configuration for ZolPo (זול-פה).

Everything that the rest of the app needs to know about *where data lives* and
*which chains we support* is declared here. Adding a new supermarket chain is
meant to be a one-entry change in ``CHAINS`` plus a matching downloader in
``ingest/`` — see docs/ADDING_A_CHAIN.md.
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
# backend/app/config.py  ->  backend/
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BACKEND_DIR, "data")
DUMPS_DIR = os.path.join(DATA_DIR, "dumps")          # data/dumps/<chain_key>/<store_id>/
DB_PATH = os.path.join(DATA_DIR, "zolpo.db")
REGISTRY_PATH = os.path.join(DATA_DIR, "stores.json")  # canonical store registry
FRONTEND_DIR = os.path.normpath(os.path.join(BACKEND_DIR, "..", "frontend"))

# --------------------------------------------------------------------------- #
# Chains
# --------------------------------------------------------------------------- #
# `id`            – small internal integer, the chain half of every store key.
# `chain_id_gov`  – the ChainID used in the government price files / filenames.
# `portal`        – which downloader in ingest/ knows how to fetch this chain.
# `cerberus_user` – login for the shared publishedprices.co.il portal (no password).
#
# The universal store key used everywhere (API, prices map, frontend selection,
# dump folders) is  f"{chain['id']}:{store_id}"  — this is what prevents a
# Rami Levy store "11" from colliding with a Shufersal store "11".
CHAINS = {
    "shufersal": {
        "key": "shufersal",
        "id": 1,
        "chain_id_gov": "7290027600007",
        "name_he": "שופרסל",
        "name_en": "Shufersal",
        "portal": "shufersal",
    },
    "rami_levy": {
        "key": "rami_levy",
        "id": 2,
        "chain_id_gov": "7290058140886",
        "name_he": "רמי לוי",
        "name_en": "Rami Levy",
        "portal": "cerberus",
        "cerberus_user": "RamiLevi",
    },
    "dor_alon": {   # the AM:PM city-convenience network
        "key": "dor_alon",
        "id": 3,
        "chain_id_gov": "7290492000005",
        "name_he": "AM:PM (דור אלון)",
        "name_en": "AM:PM",
        "portal": "cerberus",
        "cerberus_user": "doralon",
        "format_en": "AM:PM (convenience)",
    },
    "yellow": {     # Paz gas-station convenience stores
        "key": "yellow",
        "id": 4,
        "chain_id_gov": "7290644700005",
        "name_he": "yellow (פז)",
        "name_en": "Yellow",
        "portal": "cerberus",
        "cerberus_user": "Paz_bo",
        "cerberus_password": "paz468",
        "format_en": "Yellow (convenience)",
    },
    "keshet": {
        "key": "keshet",
        "id": 5,
        "chain_id_gov": "7290785400000",
        "name_he": "קשת טעמים",
        "name_en": "Keshet Teamim",
        "portal": "cerberus",
        "cerberus_user": "Keshet",
        "format_en": "Keshet (supermarket)",
        # No Tel Aviv store publishes a PriceFull today; re-run
        # scripts/build_registry.py keshet to pick them up when they appear.
    },
    "carrefour": {  # ex Yeinot Bitan / Mega
        "key": "carrefour",
        "id": 6,
        "chain_id_gov": "7290055700007",
        "name_he": "קרפור",
        "name_en": "Carrefour",
        "portal": "publishprice",
        "format_en": "Carrefour (supermarket)",
    },
}

CHAIN_BY_ID = {c["id"]: c for c in CHAINS.values()}
CHAIN_BY_GOV = {c["chain_id_gov"]: c for c in CHAINS.values()}

# Tel Aviv-Yafo municipal code in the government store directories.
TEL_AVIV_CITY_CODE = "5000"


def store_key(chain_id: int, store_id: str) -> str:
    """The universal cross-chain store key: '<chain_int>:<store_id>'."""
    return f"{chain_id}:{store_id}"


def dump_dir(chain_key: str, store_id: str) -> str:
    """Absolute path to a store's raw-download folder."""
    return os.path.join(DUMPS_DIR, chain_key, str(store_id))


# Network image enrichment during sync is OFF by default so the app boots
# instantly. Set ZOLPO_ENRICH_IMAGES=1 to query Open Food Facts during sync.
ENRICH_IMAGES = os.environ.get("ZOLPO_ENRICH_IMAGES") == "1"
