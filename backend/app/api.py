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

Accounts (users.db — separate file, see users_db.py)
  POST /api/auth/request-link   email a one-time magic sign-in link
  GET  /api/auth/verify         redeem the link → session cookie → redirect /
  POST /api/auth/logout
  GET  /api/me                  current user + synced stores + consents
  PUT  /api/me/stores           sync the store selection
  POST /api/me/consents         record a consent change (append-only ledger)
  POST /api/me/link-anon        claim this device's pre-signup events
  POST /api/events              behavioural event batch (also logged-out)
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response

from .config import CHAINS, FRONTEND_DIR
from .db import db_is_empty, get_db, init_db
from .enrich import enrich_batch
from .images import placeholder_svg
from . import compat, mailer, registry, search, users_db

log = logging.getLogger("zolpo")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    users_db.init_users_db()
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
               deals: int = Query(0, description="1 = only products with an active promo in the selected stores"),
               kind: str = Query("", description="restrict deals to one promo kind (one_plus_one, x_for_y, …)"),
               cat: str = Query("", description="comma-separated category filter (milk,cheese,…)")):
    keys = [s for s in stores.split(",") if s]
    return {"query": q,
            "results": search.search_products(q, limit, keys, deals_only=bool(deals),
                                              deal_kind=kind, categories=cat)}


@app.get("/api/deals")
def api_deals(stores: str = Query("", description="comma-separated universal store keys"),
              kind: str = Query("", description="restrict to one promo kind"),
              limit: int = Query(24, ge=1, le=100)):
    """The deals radar: products ranked by discount depth in the selected stores."""
    keys = [s for s in stores.split(",") if s]
    return {"results": search.deals_feed(keys, deal_kind=kind, limit=limit)}


@app.get("/api/cats")
def api_cats(stores: str = Query("", description="comma-separated universal store keys")):
    """Landing category tiles: per-tile product count + representative photo."""
    keys = [s for s in stores.split(",") if s]
    return {"tiles": search.category_tiles(keys)}


@app.get("/api/product/{item_code}")
def api_product(item_code: str):
    product = search.get_product(item_code)   # exact barcode match, not LIKE
    if product is None:
        raise HTTPException(status_code=404, detail="not found")
    return product


@app.get("/api/store-highlights")
def api_store_highlights(store: str = Query(..., description="universal store key, e.g. 11:024"),
                         limit: int = Query(3, ge=1, le=10)):
    """A map pin's payload: the store's top deals + biggest recent price drops."""
    return search.store_highlights(store, limit)


@app.get("/api/history/{item_code}")
def api_history(item_code: str,
                stores: str = Query("", description="comma-separated universal store keys"),
                days: int = Query(90, ge=1, le=730)):
    """Per-store price series from the append-only price_history archive."""
    keys = [s for s in stores.split(",") if s]
    return {"item_code": item_code, "days": days,
            "series": search.price_history(item_code, keys, days)}


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
        totals = conn.execute(
            """
            SELECT (SELECT COUNT(*) FROM products)  AS products,
                   (SELECT COUNT(*) FROM promos
                     WHERE end_date >= date('now')) AS active_promos
            """
        ).fetchone()
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
    return {"last_update": latest, "chains": chains,
            "products": totals["products"], "active_promos": totals["active_promos"]}


@app.get("/api/compat")
def api_compat():
    """Cross-chain barcode overlap (the comparable product set)."""
    return compat.db_overlap()


# --------------------------------------------------------------------------- #
# Accounts (users.db): magic-link auth, store sync, consents, events
# --------------------------------------------------------------------------- #

_SESSION_COOKIE = "zp_session"
_SECURE_COOKIES = os.environ.get("ZOLPO_SECURE_COOKIES") == "1"   # set in prod (HTTPS)


def _current_user(request: Request) -> dict | None:
    return users_db.session_user(request.cookies.get(_SESSION_COOKIE, ""))


def _require_user(request: Request) -> dict:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="not signed in")
    return user


@app.post("/api/auth/request-link")
def api_auth_request_link(request: Request, payload: dict = Body(...)):
    """Email a one-time sign-in link. Never reveals whether the email exists."""
    try:
        res = users_db.request_magic_link(payload.get("email", ""))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid email")
    except users_db.RateLimited:
        raise HTTPException(status_code=429, detail="try again in a minute")
    url = f"{mailer.BASE_URL}/api/auth/verify?token={res['token']}"
    out = {"sent": True}
    if not mailer.send_magic_link(res["email"], url):
        # Dev mode (no SMTP): log the link, and hand it to *localhost* clients
        # only — anything else could mint sessions for arbitrary emails.
        log.warning("SMTP not configured — magic link for %s: %s", res["email"], url)
        if request.client and request.client.host in ("127.0.0.1", "::1"):
            out["dev_link"] = url
    return out


@app.get("/api/auth/verify")
def api_auth_verify(token: str = Query(...)):
    """The link from the email: token → session cookie → back to the app."""
    res = users_db.redeem_magic_link(token)
    if res is None:
        return RedirectResponse("/?signed-in=expired")
    resp = RedirectResponse("/?signed-in=1")
    resp.set_cookie(_SESSION_COOKIE, res["session_token"],
                    max_age=users_db.SESSION_TTL_DAYS * 86400,
                    httponly=True, samesite="lax", secure=_SECURE_COOKIES)
    return resp


@app.post("/api/auth/logout")
def api_auth_logout(request: Request):
    users_db.delete_session(request.cookies.get(_SESSION_COOKIE, ""))
    resp = Response(content='{"ok": true}', media_type="application/json")
    resp.delete_cookie(_SESSION_COOKIE)
    return resp


@app.get("/api/me")
def api_me(request: Request):
    user = _current_user(request)
    if user is None:
        return {"user": None}
    return {"user": {"email": user["email"], "display_name": user["display_name"],
                     "locale": user["locale"]},
            "stores": users_db.get_user_stores(user["user_id"]),
            "consents": users_db.get_consents(user["user_id"])}


@app.put("/api/me/stores")
def api_me_stores(request: Request, payload: dict = Body(...)):
    """Server-side sync of the frontend's store selection (localStorage)."""
    user = _require_user(request)
    keys = users_db.set_user_stores(user["user_id"], payload.get("stores") or [])
    return {"stores": keys}


@app.post("/api/me/consents")
def api_me_consents(request: Request, payload: dict = Body(...)):
    user = _require_user(request)
    kind = str(payload.get("kind", ""))
    if kind not in ("analytics", "marketing", "data_insights"):
        raise HTTPException(status_code=400, detail="unknown consent kind")
    users_db.record_consent(user["user_id"], kind, bool(payload.get("granted")))
    return {"consents": users_db.get_consents(user["user_id"])}


@app.post("/api/me/link-anon")
def api_me_link_anon(request: Request, payload: dict = Body(...)):
    """Attach this device's pre-signup events to the freshly signed-in user."""
    user = _require_user(request)
    linked = users_db.link_anon(user["user_id"], payload.get("anon_id", ""))
    return {"linked": linked}


@app.post("/api/events")
def api_events(request: Request, payload: dict = Body(...)):
    """Behavioural event batch (allowlisted types; works logged-out via anon_id)."""
    user = _current_user(request)
    written = users_db.record_events(payload.get("anon_id", ""),
                                     user["user_id"] if user else None,
                                     payload.get("events") or [])
    return {"written": written}


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
