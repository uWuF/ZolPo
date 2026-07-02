"""
Download + load promotions (PromoFull) for every registry store.

    python scripts/promos.py              # download all, then ingest
    python scripts/promos.py --ingest     # ingest already-downloaded files only
"""

import _bootstrap  # noqa: F401
import json
import sys

from app import registry
from ingest.promos import download_all, ingest_promos

if __name__ == "__main__":
    registry.reload()
    if "--ingest" not in sys.argv:
        print("Downloading PromoFull files …", flush=True)
        print(json.dumps(download_all()))
    print("Ingesting promos …", flush=True)
    print(json.dumps(ingest_promos(), ensure_ascii=False))
