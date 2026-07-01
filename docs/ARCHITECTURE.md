# Architecture

ZolPo is a small FastAPI backend that serves a JSON API and a static
Alpine.js/Tailwind frontend, backed by a SQLite database that is filled from
Israel's government price-transparency files.

## Data flow

```
gov portals ──▶ ingest/ downloaders ──▶ data/dumps/<chain>/<store>/PriceFull*
                                              │
                          ingest/loader.py ───┘──▶ zolpo.db (products, stores, prices)
                                              │
                              app/ API ───────┘──▶ frontend (search, compare, basket)
```

1. **Download** (`ingest/shufersal.py`, `ingest/cerberus.py`) pulls the newest
   `PriceFull` file per store into `data/dumps/<chain_key>/<store_id>/`.
2. **Load** (`ingest/loader.py`) parses the XML and upserts `products`,
   `stores`, `prices`.
3. **Serve** (`app/api.py`) exposes search/compare endpoints and the registry.
4. **Display** (`frontend/`) lets the user pick markets and compare prices.

## Backend modules (`backend/app/`)

| Module        | Responsibility |
|---------------|----------------|
| `config.py`   | Paths + the **chain registry** (`CHAINS`) + the `store_key()` helper. The one place you edit to add a chain. |
| `db.py`       | SQLite schema, connection helper, upserts. |
| `registry.py` | Loads `data/stores.json`, injects the universal `key` + chain display names. |
| `search.py`   | Store-scoped product search (products ⟕ product_meta); per-store price maps keyed by universal key. |
| `enrich.py`   | Open Food Facts gap-filler (English names + images) into `product_meta`; manual via POST /api/enrich. |
| `images.py`   | Chain image-URL builders (Shufersal API / Rami Levy CDN), Hebrew→category guesser, SVG placeholders. |
| `compat.py`   | Cross-chain barcode overlap + name-agreement report (#7). |
| `api.py`      | FastAPI routes + static hosting. |

`backend/main.py` is a thin shim (`from app.api import app`) so the uvicorn
command never has to change.

## Ingest modules (`backend/ingest/`)

| Module          | Responsibility |
|-----------------|----------------|
| `shufersal.py`  | Download from Shufersal's open portal. |
| `cerberus.py`   | Login + download from the shared `publishedprices.co.il` portal (Rami Levy …). |
| `directory.py`  | Build Tel Aviv registry entries for a Cerberus chain from its Stores directory. |
| `geocode.py`    | Address → lat/lon (Nominatim → Photon → ZIP fallback). |
| `loader.py`     | Parse `PriceFull` XML → DB, for every registry store of any chain. |

## The two keys that make it scale

- **`item_code` (barcode)** is the product identity across chains. The DB stores
  one `products` row per barcode.
- **`chain_id:store_id`** (the *universal store key*) is the store identity. The
  DB keys `prices`/`stores` on the `(chain_id, store_id)` composite; the API and
  frontend use the `"1:11"` string form. Without this, store-number collisions
  between chains would corrupt comparisons.

## Database schema

```sql
products     (item_code PK, item_name, manufacture_name, category)          -- from gov files; reset-able
product_meta (item_code PK, item_name_en, image_url, image_source, enriched) -- derived; SURVIVES re-ingest
stores       (chain_id, store_id, store_name, city, address,  PK(chain_id, store_id))
prices       (item_code, chain_id, store_id, price, update_date,  PK(item_code, chain_id, store_id))
```

The `products` / `product_meta` split is deliberate lifecycle separation:
`scripts/ingest.py` (reset) wipes and refills everything derived *from the
price files*, while `product_meta` holds work that costs network time or money
to produce — resolved image URLs and English names. A full re-ingest keeps all
of it. `item_name_en` is the seam for proper English: the frontend shows it
verbatim when set (today OFF/manual, next an LLM batch pass), falling back to
transliteration otherwise.

## Frontend

No build step. `index.html` is markup only; logic is split into
`assets/js/{translit,i18n,api,app}.js` (loaded in that order — each attaches to
`window.ZP`, and `app.js` defines the Alpine component). Everything is keyed on
the universal store key. Chains are colour-coded (Shufersal rose, Rami Levy
blue) so a price row's chain is obvious at a glance.

## Known limitations / next steps

- Search is `LIKE` substring matching — fine for the prototype; the next step is
  autocomplete + category browse + EN→HE synonym mapping (see the design notes).
- The market picker is a checkbox list grouped by chain. At many chains/branches
  it should become **location-first** ("near me", using the lat/lon already in
  the registry).
- Tailwind runs from the CDN (a dev convenience). For production, compile it.
