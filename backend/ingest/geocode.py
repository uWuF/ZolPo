"""
Lightweight geocoder for store addresses (used to place markets on the map).

Tries Nominatim then Photon (both OSM-based), with a polite rate limit and a
ZIP-centroid fallback for the small Israeli streets OSM doesn't know. Results
are best-effort; `geo_approx=True` flags the fallback so the UI can mark it.
"""

from __future__ import annotations

import time

import requests

UA = {"User-Agent": "ZolPo/1.0 (richard.ya95@gmail.com)"}
_LAST = [0.0]


def _throttle(min_gap: float = 1.1):
    dt = time.time() - _LAST[0]
    if dt < min_gap:
        time.sleep(min_gap - dt)
    _LAST[0] = time.time()


def _nominatim(query: str) -> tuple | None:
    _throttle()
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": query, "format": "json", "limit": 1,
                                 "countrycodes": "il", "addressdetails": 1},
                         headers=UA, timeout=20)
        for hit in r.json():
            if hit.get("addresstype") in ("city", "municipality", "suburb", "state"):
                continue
            return float(hit["lat"]), float(hit["lon"]), False
    except Exception:
        pass
    return None


def _photon(query: str) -> tuple | None:
    _throttle()
    try:
        r = requests.get("https://photon.komoot.io/api",
                         params={"q": query, "limit": 1, "lang": "default"},
                         headers=UA, timeout=20)
        feats = r.json().get("features") or []
        if feats:
            lon, lat = feats[0]["geometry"]["coordinates"]
            return float(lat), float(lon), False
    except Exception:
        pass
    return None


def geocode(address: str, city: str = "תל אביב יפו", zip_code: str = "") -> dict:
    """Return {'lat', 'lon', 'geo_approx'} for an address (None coords if all fail)."""
    addr = address or ""
    # normalise "בן יהודה 79" / "האומן,15" -> "בן יהודה 79"
    addr = addr.replace(",", " ").strip()
    for q in (f"{addr}, {city}, Israel", f"{addr}, {city}"):
        for fn in (_nominatim, _photon):
            hit = fn(q)
            if hit:
                return {"lat": hit[0], "lon": hit[1], "geo_approx": hit[2]}
    # ZIP-centroid fallback
    if zip_code:
        hit = _nominatim(f"{zip_code}, Israel") or _photon(f"{zip_code}, Israel")
        if hit:
            return {"lat": hit[0], "lon": hit[1], "geo_approx": True}
    return {"lat": None, "lon": None, "geo_approx": True}
