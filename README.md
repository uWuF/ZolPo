# ZolPo · זול-פה

Real-time **Israeli supermarket price comparison**. Compare the *same product*
across stores and chains using Israel's open government price-transparency data.

The prototype covers **Tel Aviv-Yafo** with **126 stores across 8 chains**:
33 Shufersal (Sheli, Deal, Express, Be), 4 Rami Levy, 32 AM:PM, 13 Yellow (Paz),
23 Carrefour, 2 King Store, 17 Good Pharm and 2 Super Bareket — plus active
**promotions** for every store. Built to scale to more chains and cities by
adding one config entry + (sometimes) one downloader.

```
┌─────────────┐   download    ┌──────────┐  ingest   ┌──────────┐   API    ┌──────────┐
│ Gov portals │ ────────────▶ │  data/   │ ────────▶ │ zolpo.db │ ───────▶ │ frontend │
│ (per chain) │  ingest/      │  dumps/  │  loader   │ (sqlite) │  app/    │ (Alpine) │
└─────────────┘               └──────────┘           └──────────┘          └──────────┘
```

## Quick start

```bash
cd backend
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt

# Run the app (serves API + frontend on http://127.0.0.1:8020)
.venv312/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8020
```

Open <http://127.0.0.1:8020>. The DB ships populated; on an empty DB the server
auto-loads whatever is already in `data/dumps/`.

## Refresh the data

```bash
cd backend
.venv312/bin/python scripts/download.py        # pull newest price files (all chains)
.venv312/bin/python scripts/ingest.py          # load them into zolpo.db
.venv312/bin/python scripts/promos.py          # promotions for every store
.venv312/bin/python scripts/resolve_images.py --only-missing  # images for new barcodes
.venv312/bin/python scripts/off_images.py      # Open Food Facts pass (international barcodes)
.venv312/bin/python scripts/translate_names.py --run          # EN names (needs Claude auth)
.venv312/bin/python scripts/compat_report.py   # cross-chain barcode/name compatibility
```

`resolve_images.py` probes each barcode against the Shufersal storefront API and
the Rami Levy image CDN and stores the first working photo URL (~64% of the
catalog; the rest fall back to category placeholders). Images and English names
live in `product_meta`, which **survives re-ingest** — no need to re-resolve
after a data refresh. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md#product-images).

Run the unit tests after touching the pipeline or search:

```bash
backend/.venv312/bin/python backend/tests/test_zolpo.py
```

## Project layout

```
backend/
  app/            FastAPI app + domain logic (config, db, search, enrich, images, compat, registry, api)
  ingest/         data pipeline (downloaders, geocoder, XML loader, registry builder)
  scripts/        CLI entry points (download / ingest / resolve_images / build_registry / compat_report)
  tests/          unit tests (stdlib unittest, no extra deps)
  data/           zolpo.db, stores.json (registry), dumps/<chain>/<store>/, store directories
  main.py         thin shim -> app.api:app  (keeps the uvicorn command stable)
frontend/
  index.html      markup only
  assets/css      styles.css (Tailwind via CDN handles the rest)
  assets/js       translit.js · i18n.js · api.js · app.js  (load in that order)
docs/             ARCHITECTURE · DATA_SOURCES · ADDING_A_CHAIN
```

## API

| Method | Path                        | Purpose                                  |
|--------|-----------------------------|------------------------------------------|
| GET    | `/api/search?q=&stores=`    | Search; `stores` = universal keys to compare |
| GET    | `/api/product/{item_code}`  | Single product + per-store prices        |
| GET    | `/api/stores`               | Market registry (selector + map)         |
| GET    | `/api/chains`               | Supported chains                         |
| GET    | `/api/meta`                 | Last price-file timestamp + per-chain stats |
| GET    | `/api/compat`               | Cross-chain barcode overlap              |
| POST   | `/api/enrich?limit=`        | Open Food Facts batch (English names + images) |
| GET    | `/api/placeholder/{kw}.svg` | Category placeholder image               |

## Key ideas

- **Barcode is the join key.** The same `ItemCode` (EAN) means the same product
  in every chain. Names are *not* reliable — each chain abbreviates differently
  (see `scripts/compat_report.py`), so we compare on barcode and display the
  nicest available name.
- **Universal store key `chain_int:store_id`** (e.g. `1:11`, `2:733`) is used
  everywhere — API, price maps, the frontend selection, dump folders. This is
  what stops a Rami Levy store `11` from colliding with a Shufersal store `11`.
- **Adding a chain is a config + downloader change**, not a rewrite. See
  [docs/ADDING_A_CHAIN.md](docs/ADDING_A_CHAIN.md).

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
