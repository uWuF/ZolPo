"""
Cross-chain product compatibility (#7).

Our whole comparison model rests on one assumption: the same barcode (ItemCode)
means the same product in every chain. This module checks that assumption two
ways:

  db_overlap()      – how many barcodes are priced in each chain, and how many
                      are shared (the comparable set). Cheap, runs off the DB.
  raw_name_compat() – for shared barcodes, do the chains agree on the *name*?
                      A high agreement rate confirms barcode == product; the
                      mismatches it surfaces are usually packaging/size wording,
                      not wrong mappings. Reads the raw PriceFull dumps because
                      the DB keeps only one name per barcode.
"""

from __future__ import annotations

import re

from .config import CHAINS
from .db import get_db


def db_overlap() -> dict:
    """Per-chain barcode counts + pairwise shared-barcode counts, from the DB."""
    with get_db() as conn:
        per_chain = {}
        sets = {}
        for chain in CHAINS.values():
            codes = {r["item_code"] for r in conn.execute(
                "SELECT DISTINCT item_code FROM prices WHERE chain_id = ?", (chain["id"],)
            ).fetchall()}
            if codes:
                sets[chain["key"]] = codes
                per_chain[chain["key"]] = len(codes)

    pairwise = []
    keys = list(sets)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            pairwise.append({"chains": [a, b], "shared": len(sets[a] & sets[b])})
    shared_all = len(set.intersection(*sets.values())) if len(sets) > 1 else 0
    return {"per_chain": per_chain, "pairwise": pairwise, "shared_all_chains": shared_all}


# --------------------------------------------------------------------------- #
# Name agreement (raw)
# --------------------------------------------------------------------------- #

def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def _tokens(name: str) -> set:
    return set(re.sub(r"[^\w%]", " ", _norm(name)).split())


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def raw_name_compat(max_examples: int = 12) -> dict:
    """
    Build {barcode: {chain_key: name}} from one representative store per chain and
    score name agreement for barcodes that appear in 2+ chains.
    """
    # Imported lazily so app/ has no hard dependency on ingest/.
    from ingest.loader import iter_items, newest_pricefull
    from . import registry

    # Pick one store per chain (the first registry entry of that chain with a file).
    by_barcode: dict[str, dict[str, str]] = {}
    used = {}
    for s in registry.all_stores():
        ck = s.get("chain_key")
        if ck in used:
            continue
        path = newest_pricefull(ck, s.get("store_id"))
        if not path:
            continue
        used[ck] = s.get("store_id")
        for code, name, _manuf, _price in iter_items(path):
            by_barcode.setdefault(code, {})[ck] = name

    shared = {c: names for c, names in by_barcode.items() if len(names) >= 2}
    exact = high = 0
    examples = []
    for code, names in shared.items():
        vals = list(names.values())
        sim = min(_similarity(vals[0], v) for v in vals[1:])
        if all(_norm(vals[0]) == _norm(v) for v in vals[1:]):
            exact += 1
        elif sim >= 0.4:
            high += 1
        elif len(examples) < max_examples:
            examples.append({"barcode": code, "names": names, "similarity": round(sim, 2)})

    total = len(shared)
    return {
        "representative_stores": used,
        "shared_barcodes": total,
        "exact_name_match": exact,
        "similar_name_match": high,
        "agreement_pct": round(100 * (exact + high) / total, 1) if total else 0.0,
        "mismatch_examples": examples,
    }
