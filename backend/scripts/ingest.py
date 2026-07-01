"""
Load every registry store's downloaded PriceFull into zolpo.db.

    python scripts/ingest.py            # reset + reload all chains
    python scripts/ingest.py --keep     # add/update without clearing tables
"""

import _bootstrap  # noqa: F401
import json
import sys

from ingest.loader import ingest_registry
from app import registry

if __name__ == "__main__":
    keep = "--keep" in sys.argv
    registry.reload()
    result = ingest_registry(reset=not keep)
    ok = [s for s in result["stores"] if "products" in s]
    err = [s for s in result["stores"] if "error" in s]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nLoaded {len(ok)} stores, {sum(s['products'] for s in ok):,} price rows; {len(err)} errors.")
