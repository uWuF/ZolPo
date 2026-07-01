"""
Cross-chain product compatibility report (#7).

    python scripts/compat_report.py

Answers: how many barcodes are shared between chains (the comparable set), and
do the chains agree on product names for shared barcodes?
"""

import _bootstrap  # noqa: F401
import json

from app import compat

if __name__ == "__main__":
    print("=== Barcode overlap (from DB) ===")
    print(json.dumps(compat.db_overlap(), ensure_ascii=False, indent=2))
    print("\n=== Name agreement on shared barcodes (from raw files) ===")
    print(json.dumps(compat.raw_name_compat(), ensure_ascii=False, indent=2))
