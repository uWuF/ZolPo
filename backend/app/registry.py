"""
The store registry: data/stores.json.

This file is the single source of truth for the market selector and the (future)
map. The DB knows prices keyed by (chain_id, store_id); the registry adds the
human layer — labels, address, coordinates, format — and the universal `key`
that ties a registry entry to its DB prices.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .config import REGISTRY_PATH, CHAINS, store_key

# Fields exposed to the frontend via /api/stores.
_PUBLIC_FIELDS = (
    "uuid", "key", "chain", "chain_key", "chain_en", "chain_he", "chain_id", "store_id",
    "subchain_id", "format", "format_en",
    "label_en", "label_he", "store_name",
    "city", "address", "lat", "lon", "geo_approx",
)


@lru_cache(maxsize=1)
def _load_raw() -> list:
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def reload() -> None:
    """Drop the cache after a registry rebuild."""
    _load_raw.cache_clear()


def all_stores() -> list:
    """Every registry entry, normalised with a universal `key`."""
    out = []
    for s in _load_raw():
        chain = CHAINS.get(s.get("chain_key", ""), {})
        chain_int = s.get("chain_int") or chain.get("id")
        entry = dict(s)
        if chain_int is not None and s.get("store_id") is not None:
            entry["key"] = store_key(chain_int, s["store_id"])
        entry["chain_en"] = chain.get("name_en")
        entry["chain_he"] = chain.get("name_he")
        out.append(entry)
    return out


def public_stores() -> list:
    """The trimmed view the frontend consumes."""
    return [{k: s.get(k) for k in _PUBLIC_FIELDS} for s in all_stores()]
