"""
(Re)build data/stores.json — the canonical market registry.

    python scripts/build_registry.py rami_levy        # rebuild one chain's TA stores
    python scripts/build_registry.py                  # just normalise existing entries

Existing entries for chains you don't pass are preserved (so the already-geocoded
Shufersal stores are never re-fetched). Cerberus chains you pass are rebuilt from
their live Stores directory.
"""

import _bootstrap  # noqa: F401
import json
import os
import sys

from app.config import CHAINS, REGISTRY_PATH, BACKEND_DIR, store_key
from ingest.directory import build_tel_aviv_registry

LEGACY_PATH = os.path.join(BACKEND_DIR, "stores.json")  # pre-refactor location


def _load_existing() -> list:
    for path in (REGISTRY_PATH, LEGACY_PATH):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return []


def _normalise(entry: dict) -> dict:
    """Backfill the universal key + chain_int/chain_key on legacy entries."""
    if not entry.get("chain_key"):
        # Legacy entries were all Shufersal.
        gov = entry.get("chain_id")
        ck = next((c["key"] for c in CHAINS.values() if c["chain_id_gov"] == gov), "shufersal")
        entry["chain_key"] = ck
    chain = CHAINS.get(entry["chain_key"], {})
    entry["chain_int"] = entry.get("chain_int") or chain.get("id")
    if entry.get("store_id") and entry.get("chain_int"):
        entry["key"] = store_key(entry["chain_int"], entry["store_id"])
    entry["dump"] = f"{entry['chain_key']}/{entry['store_id']}"  # canonical, under data/dumps/
    return entry


def main(rebuild_chains: list[str]) -> None:
    registry = [_normalise(e) for e in _load_existing()]

    for ck in rebuild_chains:
        if ck not in CHAINS:
            print(f"!! unknown chain '{ck}' — skipping")
            continue
        print(f"Rebuilding Tel Aviv stores for '{ck}' …")
        fresh = build_tel_aviv_registry(ck)
        registry = [e for e in registry if e.get("chain_key") != ck] + fresh
        print(f"   {len(fresh)} stores: {[e['store_id'] for e in fresh]}")

    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)

    by_chain = {}
    for e in registry:
        by_chain[e["chain_key"]] = by_chain.get(e["chain_key"], 0) + 1
    print(f"Wrote {len(registry)} stores -> {REGISTRY_PATH}")
    print("Per chain:", by_chain)


if __name__ == "__main__":
    main(sys.argv[1:])
