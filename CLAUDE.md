# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZolPo (זול-פה) — Israeli supermarket price-comparison PWA. FastAPI + SQLite backend
ingests Israel's government price-transparency XML feeds (per-chain, per-store
`PriceFull`/`PromoFull` files); a no-build Alpine.js/Tailwind frontend lets users
compare the same barcode across chains. Currently scoped to Tel Aviv-Yafo (189
stores, 14 chains).

## Commands

Setup:
```bash
cd backend
python3.12 -m venv .venv312
.venv312/bin/pip install -r requirements.txt
```

Run the app (serves API + static frontend on port 8020):
```bash
backend/.venv312/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8020
```
The DB ships populated; on an empty DB the server auto-loads whatever is already
downloaded into `backend/data/dumps/`.

Run tests (stdlib `unittest`, zero extra deps — fits the no-build philosophy):
```bash
backend/.venv312/bin/python backend/tests/test_zolpo.py -v
# or, from backend/:
.venv312/bin/python -m pytest tests/ -q
```
Run after touching `ingest/` (filename/timestamp parsing per portal),
`app/search.py` (store-key parsing, price/promo attachment), `app/images.py`
(category guesser), or `ingest/promos.py` (promo kind classification) — these
carry the most regex/parsing logic and the most regression coverage.

Refresh data (run in order from `backend/`; each step is independently
resumable and safe to re-run):
```bash
.venv312/bin/python scripts/download.py                         # newest price/promo files, all chains
.venv312/bin/python scripts/ingest.py                            # reset + reload (use --keep to skip the reset)
.venv312/bin/python scripts/promos.py                            # promotions for every store
.venv312/bin/python scripts/resolve_images.py --only-missing     # images for new barcodes
.venv312/bin/python scripts/off_images.py                        # Open Food Facts pass (international barcodes)
.venv312/bin/python scripts/translate_names.py --run             # EN names (needs Claude auth)
.venv312/bin/python scripts/compat_report.py                     # cross-chain barcode/name overlap
```

Frontend has no build step — edit files directly under `frontend/assets/`.
**Bump the `?v=N` query param on every `<script>`/`<link>` tag in
`frontend/index.html` whenever any JS/CSS asset changes** — the HTML is served
`Cache-Control: no-cache` but assets are cache-busted only by that version
number, so browsers otherwise keep serving stale JS/CSS.

## Architecture

### Data flow
```
gov portals ──▶ ingest/ downloaders ──▶ data/dumps/<chain>/<store>/{PriceFull,PromoFull}*
                                              │
                    ingest/loader.py + ingest/promos.py ──▶ zolpo.db
                                              │
                                    app/api.py (FastAPI) ──▶ frontend/ (Alpine.js)
```

### The two keys that make cross-chain comparison work
- **Barcode (`item_code`, EAN)** is the only reliable product-identity join key
  across chains — product names are chain-specific abbreviations and are never
  used for matching, only for display.
- **Universal store key `"<chain_int>:<store_id>"`** (e.g. `"1:11"`, `"2:733"`)
  is used everywhere: API query params, price/promo maps, frontend selection
  state (`localStorage`), dump folder paths. Without it, store `"11"` at one
  chain would collide with store `"11"` at another.

### Chain config is additive, not a rewrite (`backend/app/config.py`)
`CHAINS` is a dict keyed by chain slug; each entry has a stable integer `id`
(the chain half of every store key — never reuse or renumber), `chain_id_gov`
(the ChainID in the gov files), and a `portal` value that selects a downloader
in `backend/ingest/`:
- `cerberus` — shared `publishedprices.co.il` portal (most chains: Rami Levy,
  AM:PM, Yellow, Tiv Taam, Osher Ad, Fresh Market…), per-chain username, no/simple
  password (these are public transparency-law credentials, not secrets).
- `shufersal` — Shufersal's own open portal.
- `publishprice` — Carrefour's PublishPrice portal.
- `bina` — Bina portal family (King Store, Good Pharm, Bareket).
- `superpharm`, `wolt`, `citymarket` — each chain's own bespoke portal shape.

Adding a new chain on an already-supported portal is normally just a `CHAINS`
entry + `scripts/build_registry.py <chain>` — see `docs/ADDING_A_CHAIN.md`.
Portal quirks (XML dialect differences, filename formats, stub/empty-file
edge cases) are documented in `docs/DATA_SOURCES.md` and in each
`ingest/<portal>.py` module's docstring.

### `products` vs `product_meta` vs `price_history` — deliberate lifecycle split
`products` (name, category, manufacturer) is wiped and rebuilt wholesale on
every `scripts/ingest.py` run (unless `--keep`) — it's a direct projection of
the current gov price files. `product_meta` (English name, image URL/source)
is enrichment that costs network time or money to produce and **survives
reset ingests**; never derive it inside the reset path, and `upsert_product`
must not let a later chain's empty name blank out an already-known one.
`price_history` is append-only and also **survives resets** — every ingest
ends with `record_price_history()` (db.py), which archives delta-compressed
observations (a row per (item, store, day) only when the price first appears
or changes). It can never be rebuilt from a later download (portals serve only
current files), so no code path may ever DELETE from it. Served by
`GET /api/history/{item_code}`; it's the substrate for price graphs,
deal-honesty checks and alerts.

### Promotions (`ingest/promos.py`)
Two XML dialects across chains: `<Item>` + `PromotionEndDate` (Cerberus/Bina
family) vs `<PromotionItem>` + `PromotionEndDateTime` (Shufersal family, Wolt,
Super-Pharm) — `_iter_items()` reads both. `classify_promo()` buckets each
promo into `one_plus_one / x_for_y / percent_off / fixed_price / club / other`
from the Hebrew description text plus `MinQty`/`DiscountedPrice`. A bare `%` in
a description is usually a product spec (fat %, ABV), not a discount —
`percent_off` requires actual discount phrasing ("X% הנחה", "הנחה של X%", "X%
על", "השני ב-X%"); see the regression cases in
`test_zolpo.py::ClassifyPromo`. Per-item unit price convention, used both by
the backend's deals ranking (`search.py:deals_feed`) and the frontend's
per-store price display: `DiscountedPrice / max(MinQty, 1)`.

A store's promo is only surfaced as an effective price when that same store
also has a **shelf price** for the barcode — see `carries()` in
`frontend/assets/js/app.js` and the `store_price` CTE in `search.py:deals_feed`.
A promo with no matching `PriceFull` row is not evidence the item is stocked
there; treat it as not carried, not as a phantom price.

### Categories (`app/images.py`, `app/search.py`)
`guess_category()` maps a Hebrew product name to one of ~26 fine-grained
buckets (Wolt-Market-style: dairy, produce, alcohol, frozen, baby, pet,
canned, baking, deli…) via ordered keyword lists — **order matters**: flavour
and brand words are checked before generic food words (e.g. snack/sweet
keywords before produce, so "onion Bissli" doesn't land in vegetables), and
needles are matched against a space-padded name to get word-boundary behavior.
`TILES` in `search.py` groups the fine categories into the landing page's
browse tiles; `category_tiles()` picks each tile's representative photo from a
curated hero-barcode list first, falling back to the most cross-store-covered
product in that tile that has a resolved image.

### Frontend (no build step)
`frontend/index.html` is markup only. `frontend/assets/js/{translit,i18n,api,app}.js`
must load in that order — each attaches to `window.ZP`, and `app.js`'s Alpine
component reads off it. The landing page (`homeMode()` in `app.js`, true when
there's no query/filter/category active) shows a hero + deals radar + category
tile grid and fires **no catalog query** until the user searches, filters, or
picks a category — don't reintroduce an unscoped `/api/search` call at boot.
Everything is keyed on the universal store key; chains are colour-coded via
`CHAIN_COLOR` in `app.js` so a price row's chain is obvious at a glance.

## Further reading
- `docs/ARCHITECTURE.md` — module-by-module responsibility tables, DB schema.
- `docs/DATA_SOURCES.md` — per-chain portal details, credentials, image sourcing.
- `docs/ADDING_A_CHAIN.md` — step-by-step checklist for a new chain.
