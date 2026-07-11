"""
Refresh the raw PriceFull files for every store in the registry.

    python scripts/download.py                 # all chains
    python scripts/download.py shufersal       # one chain

Shufersal stores use the open Shufersal portal; Cerberus chains (Rami Levy …)
share one logged-in session.
"""

import _bootstrap  # noqa: F401
import sys

from app.config import CHAINS, dump_dir
from app import registry
from ingest import bina, citymarket, publishprice, shufersal, superpharm, wolt
from ingest.cerberus import CerberusClient, download_store_pricefull


def main(only: list[str]) -> None:
    stores = registry.all_stores()
    chains = only or sorted({s["chain_key"] for s in stores})

    for ck in chains:
        chain = CHAINS.get(ck)
        if not chain:
            print(f"!! unknown chain {ck}"); continue
        targets = [s for s in stores if s["chain_key"] == ck]
        print(f"{chain['name_en']}: {len(targets)} stores")
        try:
            _download_chain(chain, ck, targets)
        except Exception as e:
            # One broken or geo-blocked portal must never kill the whole
            # refresh — every other chain still gets fresh prices, and the
            # ingest step will use this chain's newest files already on disk.
            print(f"   !! {chain['name_en']} FAILED: {type(e).__name__}: {e}")


def _download_chain(chain: dict, ck: str, targets: list[dict]) -> None:
    if chain["portal"] == "cerberus":
        client = CerberusClient(chain["cerberus_user"],
                                chain.get("cerberus_password", "")).login()
        names = client.list_files("PriceFull")
        for s in targets:
            p = download_store_pricefull(client, s["store_id"], dump_dir(ck, s["store_id"]), names=names)
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")
    elif chain["portal"] == "publishprice":
        files = publishprice.list_files(days_back=2)
        for s in targets:
            p = publishprice.download_store_pricefull(files, s["store_id"], dump_dir(ck, s["store_id"]))
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")
    elif chain["portal"] == "bina":
        names = bina.list_files(chain["bina_prefix"], "PriceFull")
        for s in targets:
            p = bina.download_store_file(chain["bina_prefix"], s["store_id"],
                                         dump_dir(ck, s["store_id"]), names)
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")
    elif chain["portal"] == "superpharm":
        files = superpharm.list_files("PriceFull", {s["store_id"] for s in targets})
        for s in targets:
            p = superpharm.download_store_file(s["store_id"], dump_dir(ck, s["store_id"]), files)
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")
    elif chain["portal"] == "wolt":
        files = wolt.list_files(days_back=2)
        for s in targets:
            p = wolt.download_store_file(files, s["store_id"], dump_dir(ck, s["store_id"]))
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")
    elif chain["portal"] == "citymarket":
        rows = citymarket.list_rows()
        for s in targets:
            p = citymarket.download_store_file(rows, s["store_id"],
                                               dump_dir(ck, s["store_id"]), min_kb=5.0)
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")
    else:  # shufersal open portal
        for s in targets:
            p = shufersal.download_store_pricefull(s["store_id"], dump_dir(ck, s["store_id"]))
            print(f"   {s['store_id']}: {'ok' if p else 'NO FILE'}")


if __name__ == "__main__":
    main(sys.argv[1:])
