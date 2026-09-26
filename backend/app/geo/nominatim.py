import json
import time

import httpx

from app.db import ROOT

URL = "https://nominatim.openstreetmap.org/search"
CACHE = ROOT / "data/layers/nominatim_cache.json"
_last = [0.0]
TOWN = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "quarter", "municipality", "locality", "isolated_dwelling"}


def _cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def lookup(q):
    """Raw cached Nominatim hit for a free-text query, or None."""
    cache = _cache()
    if q not in cache:
        time.sleep(max(0.0, 1.1 - (time.time() - _last[0])))  # nominatim policy: 1 request per second
        _last[0] = time.time()
        try:
            r = httpx.get(URL, params={"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
                          headers={"User-Agent": "opencrew/0.1 (hackathon)"}, timeout=30)
            hits = r.json() if r.status_code == 200 else []
        except httpx.HTTPError:
            return None  # not cached, try again next run
        cache[q] = hits[0] if hits else None
        CACHE.write_text(json.dumps(cache))
    return cache[q]


def precision(hit):
    kind = hit.get("addresstype") or hit.get("type") or ""
    if kind in ("house", "building") or hit.get("category") == "building":
        return "exact"
    if kind == "road" or hit.get("category") == "highway" or hit.get("class") == "highway":
        return "road"
    if kind in TOWN:
        return "town"
    return {"county": "county", "state": "state"}.get(kind, "town")


def geocode(state_name, place):
    hit = lookup(f"{place}, {state_name}")
    if not hit:
        return None
    return {"lat": float(hit["lat"]), "lon": float(hit["lon"]), "conf": 0.5, "via": f"nominatim:{hit.get('type')}", "name": hit.get("display_name")}
