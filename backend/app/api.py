"""
ZolPo JSON API + static hosting of the frontend SPA.

Routes
  GET  /api/search       name / brand / barcode, scoped to selected stores
  GET  /api/product/{c}  one product by barcode
  GET  /api/stores       the market registry (selector + map)
  GET  /api/chains       supported chains
  GET  /api/meta         last price-file timestamp + per-chain stats
  GET  /api/compat       cross-chain barcode overlap
  POST /api/enrich       Open Food Facts batch (English names + images)
  GET  /api/placeholder/{keyword}.svg
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .config import CHAINS, FRONTEND_DIR
from .db import db_is_empty, get_db, init_db
from .enrich import enrich_batch
from .images import placeholder_svg
from . import compat, registry, search

log = logging.getLogger("zolpo")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    if db_is_empty():
        # Auto-fill from whatever has already been downloaded so a fresh checkout
        # is usable without a manual ingest step.
        try:
            from ingest.loader import ingest_registry
            ingest_registry(reset=False)
        except Exception:
            log.exception("startup auto-ingest failed; serving an empty catalog")
    yield


app = FastAPI(title="ZolPo API", version="2.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

@app.get("/api/search")
def api_search(q: str = Query("", description="name / brand / barcode"),
               limit: int = Query(60, ge=1, le=200),
               stores: str = Query("", description="comma-separated universal store keys, e.g. 1:11,2:733"),
               deals: int = Query(0, description="1 = only products with an active promo in the selected stores")):
    keys = [s for s in stores.split(",") if s]
    return {"query": q,
            "results": search.search_products(q, limit, keys, deals_only=bool(deals))}


@app.get("/api/product/{item_code}")
def api_product(item_code: str):
    product = search.get_product(item_code)   # exact barcode match, not LIKE
    if product is None:
        raise HTTPException(status_code=404, detail="not found")
    return product


@app.get("/api/stores")
def api_stores():
    return registry.public_stores()


@app.get("/api/chains")
def api_chains():
    return [{"id": c["id"], "key": c["key"], "name_en": c["name_en"], "name_he": c["name_he"]}
            for c in CHAINS.values()]


@app.get("/api/meta")
def api_meta():
    """Last published timestamp + per-chain product/store counts."""
    chains = []
    latest = None
    with get_db() as conn:
        for chain in CHAINS.values():
            row = conn.execute(
                """
                SELECT MAX(update_date) AS last_update,
                       COUNT(DISTINCT item_code) AS products,
                       COUNT(DISTINCT store_id)  AS stores
                FROM prices WHERE chain_id = ?
                """,
                (chain["id"],),
            ).fetchone()
            lu = row["last_update"] if row else None
            if lu and (latest is None or lu > latest):
                latest = lu
            chains.append({
                "name_en": chain["name_en"], "name_he": chain["name_he"],
                "stores": row["stores"] if row else 0,
                "products": row["products"] if row else 0,
                "last_update": lu,
            })
    return {"last_update": latest, "chains": chains}


@app.get("/api/compat")
def api_compat():
    """Cross-chain barcode overlap (the comparable product set)."""
    return compat.db_overlap()


# --------------------------------------------------------------------------- #
# Enrichment / assets
# --------------------------------------------------------------------------- #

@app.post("/api/enrich")
def api_enrich(limit: int = Query(40, ge=1, le=200)):
    return enrich_batch(limit)


@app.get("/api/placeholder/{keyword}.svg")
def api_placeholder(keyword: str):
    return Response(content=placeholder_svg(keyword), media_type="image/svg+xml")


# --------------------------------------------------------------------------- #
# Static frontend (mounted last so /api/* wins)
# --------------------------------------------------------------------------- #

def _index() -> FileResponse:
    # The HTML must always revalidate, or browsers keep a stale page that points
    # at old asset versions (assets themselves are cache-busted via ?v=N).
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return _index()


@app.get("/{path:path}")
def static_files(path: str):
    safe = os.path.normpath(os.path.join(FRONTEND_DIR, urllib.parse.unquote(path)))
    # commonpath (not startswith) so "../frontend_evil" can't slip past the check.
    try:
        inside = os.path.commonpath([FRONTEND_DIR, safe]) == FRONTEND_DIR
    except ValueError:
        inside = False
    if inside and os.path.isfile(safe):
        return FileResponse(safe)
    return _index()
