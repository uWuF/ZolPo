# Adding a chain

The design goal: a new chain is **a config entry + (maybe) a downloader**, not a
rewrite. Here's the whole procedure.

## 1. Register the chain (`backend/app/config.py`)

Add an entry to `CHAINS`. Pick the next free integer `id` — it becomes the chain
half of every store key, so it must be stable forever.

```python
"yohananof": {
    "key": "yohananof",
    "id": 3,                          # next free integer
    "chain_id_gov": "7290803800003",  # ChainID from the gov files
    "name_he": "יוחננוף",
    "name_en": "Yohananof",
    "portal": "cerberus",             # "cerberus" or "shufersal" or a new one
    "cerberus_user": "yohananof",     # only for cerberus chains
},
```

That's the only change for any chain whose portal is already supported
(`cerberus` or `shufersal`).

## 2. (Only if the portal is new) add a downloader

Most Israeli chains publish on the shared Cerberus portal, so usually you skip
this. If the chain has its own portal, add `ingest/<portal>.py` exposing:

```python
def download_store_pricefull(store_id: str, out_dir: str) -> str | None: ...
```

and branch on `chain["portal"]` in `scripts/download.py`.

## 3. Build the registry entries

For a Cerberus chain, `ingest/directory.py` already does everything — reads the
Stores directory, keeps Tel Aviv (city 5000), keeps only stores with a live
`PriceFull`, downloads them, geocodes the addresses:

```bash
cd backend
.venv312/bin/python scripts/build_registry.py yohananof
```

This rewrites `data/stores.json`, preserving every other chain's entries.

> For a non-Cerberus chain, write a small builder modelled on
> `build_tel_aviv_registry()` (you need each store's id, name, address, city).
> Add nice English labels in `RAMI_LEVY_LABELS_EN`-style maps if you want them.

## 4. Load into the DB

```bash
.venv312/bin/python scripts/ingest.py
```

## 5. Verify

```bash
.venv312/bin/python scripts/compat_report.py   # how many barcodes overlap the existing chains?
```

Then start the app — the new chain appears as its own group in the market
selector, colour-coded automatically (add a colour in
`frontend/assets/js/app.js` → `CHAIN_COLOR` if you want a specific one).

## Checklist

- [ ] `CHAINS` entry with a unique integer `id`
- [ ] downloader exists for `portal` (reuse cerberus/shufersal where possible)
- [ ] `scripts/build_registry.py <chain>` ran and updated `data/stores.json`
- [ ] `scripts/ingest.py` ran (stores show non-zero products)
- [ ] `CHAIN_COLOR` has a colour for the chain (optional)
- [ ] spot-check a shared barcode in the UI shows both chains' prices
