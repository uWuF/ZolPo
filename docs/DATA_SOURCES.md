# Data sources

All prices come from Israel's **price-transparency regulation** (חוק שקיפות
מחירים): every large retailer must publish machine-readable price files. The
master list of chains and their portals lives at
<https://www.gov.il/he/pages/cpfta_prices_regulations>.

## File types (per chain, per store)

| File          | catID | Contents |
|---------------|-------|----------|
| `PriceFull*`  | 2     | Full price list (what ZolPo ingests) |
| `Price*`      | 1     | Incremental price updates |
| `PromoFull*` / `Promo*` | 4 / 3 | Promotions |
| `Stores*`     | 5     | Store directory (id, name, address, city code) |

Filenames encode the chain and store, in one of two layouts:

```
PriceFull<ChainID>-<SubChainID>-<StoreID>-<YYYYMMDD>-<HHMMSS>     (e.g. Shufersal)
PriceFull<ChainID>-<StoreID>-<YYYYMMDDHHMM>                       (Rami Levy "format B")
```

`ingest/loader.py:publish_ts()` handles both. City is a **numeric code** in the
Stores directory — **Tel Aviv-Yafo = 5000**.

## Chains currently wired

### Shufersal — open portal (no login)
- ChainID `7290027600007`
- Portal: `https://prices.shufersal.co.il/FileObject/UpdateCategory?catID=2&storeId=<id>`
- Returns HTML with HTML-escaped, signed Azure blob URLs.
- SubChains: `1` שלי (Sheli supermarket), `2` דיל (Deal hyper), `5` Be (drugstore),
  `7` אקספרס (Express convenience). Tel Aviv has 33 stores across these formats.
- Downloader: `ingest/shufersal.py`.

### Rami Levy — Cerberus portal (login, blank password)
- ChainID `7290058140886`
- Portal: `https://url.retail.publishedprices.co.il/` (a.k.a. `url.publishedprices.co.il`)
- Username `RamiLevi`, **no password**.
- Tel Aviv stores (city 5000): `733` Ben Yehuda 23, `734` Esther HaMalka 4,
  `735` HaChashmonaim 100, `736` Shocken 1, `737` Ben Yehuda 174, `055` Ramat HaChayal.
  Live `PriceFull` currently exists for **733, 734, 736, 737** (we only register
  stores that have a downloadable file).
- Downloader: `ingest/cerberus.py`.

### AM:PM / Dor Alon — Cerberus (username `doralon`)
- ChainID `7290492000005`. 32 Tel Aviv AM:PM branches with live PriceFull.

### Yellow (Paz) — Cerberus (username `Paz_bo`, password `paz468`)
- ChainID `7290644700005`. 13 Tel Aviv gas-station convenience stores.
- (These portal credentials are public, published for the transparency law.)

### Carrefour (ex Yeinot Bitan / Mega) — PublishPrice portal (no login)
- ChainID `7290055700007`
- Portal: `https://prices.carrefour.co.il/` — the index page embeds the day's
  file list in inline JS (`const path/files`); `?date=YYYYMMDD` selects a day,
  files download from `/<path>/<name>`. The "today" folder fills up gradually
  overnight, so `ingest/publishprice.py` merges the last two days.
- 23 Tel Aviv branches.

### King Store / Good Pharm / Super Bareket — Bina portal (no login)
- `http://<prefix>.binaprojects.com/` — `MainIO_Hok.aspx?WFileType=<t>` returns a
  JSON file listing (1=Stores, 4=PriceFull, 5=PromoFull); `Download.aspx?FileNm=`
  returns `[{SPath: real-url}]`. Payloads are ZIP despite the `.gz` extension.
- Prefixes: `kingstore` (2 TA stores), `goodpharm` (17), `superbareket` (2).
- Downloader: `ingest/bina.py`. Other Bina chains (Zol VeBegadol, Super Sapir,
  Maayan 2000, Shuk HaIr, Shefa …) have **no Tel Aviv branches**.

### Promotions (all portals)
Every portal also publishes `PromoFull` per store (Shufersal `catID=4`, Cerberus
and Bina by file prefix, PublishPrice from the same folder listing).
`ingest/promos.py` + `scripts/promos.py` download and load them into
`promos`/`promo_items`; the API serves only promos whose `end_date` hasn't
passed, and `/api/search?deals=1` filters to promoted products.

### Probed and currently unavailable (state as of 2026-07-02)
- **Tiv Taam** (`TivTaam`) and **Cofix** (`SuperCofixApp`): Cerberus login works
  but the portals hold **no PriceFull files** at all right now.
- **Keshet** (`Keshet`): publishes, but its single Tel Aviv store (`091`) has no
  live file. A `CHAINS` entry exists; re-run `build_registry.py keshet` later.
- **Super Yuda** (`yuda_ho`) / **Fresh Market** (`freshmarket`): Cerberus, but no
  usable Stores directory (files nested in a folder / directory missing).
- **Victory** (`laibcatalog.co.il` JSON API `/webapi/api/getbranches`): API works
  but the branch list has **no Tel Aviv location** — nothing to add.
- **Super-Pharm** (own paginated portal): drugstore segment already covered by
  Good Pharm + Shufersal Be; dedicated client deferred.
- Yohananof, Osher Ad, Stop Market, Salach Dabach, Politzer: reachable via
  Cerberus but **no Tel Aviv branches** (or none with live files).

> The TLS chain on publishedprices omits an intermediate cert; `truststore`
> (in requirements) lets Python use the OS trust store to verify it.

## The shared Cerberus portal (future chains)

The same `publishedprices.co.il` login flow serves many chains — each with its
own username and a blank password. So `ingest/cerberus.py` already unlocks most
of the roadmap; adding one is mostly a `CHAINS` entry. Common usernames:

| Chain          | Username      |
|----------------|---------------|
| Rami Levy      | `RamiLevi`    |
| Yohananof      | `yohananof`   |
| Osher Ad       | `osherad`     |
| Tiv Taam       | `TivTaam`     |
| Stop Market    | `Stop_Market` |
| Dor Alon       | `doralon`     |

(Verify against the gov master list before relying on any of these — usernames
do change.)

## Product images

The government price files carry **no images**, so we source product shots from
the chains' own public storefronts, keyed by the barcode. `scripts/resolve_images.py`
probes each barcode and stores the first working URL in `product_meta.image_url`
(with `image_source`) — the enrichment table that survives re-ingest; the
frontend falls back to a category SVG placeholder when
there is none (or the URL 404s, via `<img onerror>`).

| Source | Lookup | Coverage |
|--------|--------|----------|
| **Shufersal** | storefront product API `…/online/he/products/P_<barcode>` → Cloudinary URL in the JSON `images[]` | ~63% |
| **Rami Levy** | direct image CDN `https://img.rami-levy.co.il/product/<barcode>/small.jpg` | ~24% |
| Open Food Facts | `app/enrich.py` barcode lookup (`image_front_url`) | ~1% |

With both chains + cross-fallback this resolves **~71%** of the ~20k catalog.
Notes:

- Shufersal isn't searchable by EAN, and its image is keyed by an internal code,
  **but newer SKUs use `P_<barcode>` as that code**, so the product endpoint is a
  barcode-addressable path. Legacy SKUs (short codes) miss — that's most of the
  remaining ~29%; a name-search matcher could recover some later.
- Rami Levy hosts images only for its own assortment, so its standalone coverage
  is low across the (Shufersal-heavy) catalog, but it **rescues** Rami-Levy-only
  products that Shufersal lacks — the reason we keep both with fallback.

Both are public storefront endpoints (no auth); identify with a real User-Agent
and keep concurrency modest (the script uses 8 workers).

## Open Food Facts (enrichment, not prices)

`app/enrich.py` looks up barcodes on `il.openfoodfacts.org` (then the world host)
for an English name and a product image. One request per barcode; results are
cached via `product_meta.enriched`. Identify with a real User-Agent and stay polite
(the code sleeps ~0.4 s between calls and backs off on HTTP 429). For images it's
a last resort — coverage of Israeli products is ~1% (see the table above).
