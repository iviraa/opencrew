import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.db import ROOT

MIRRORS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
LATS, LONS = [30.3, 31.6, 32.8, 34.0, 35.3], [-85.7, -83.9, -82.1, -80.3, -78.5]
TILES = [(s, w, n, e) for s, n in zip(LATS, LATS[1:]) for w, e in zip(LONS, LONS[1:])]  # GA + SC in 16 tiles
QUERY = '[out:json][timeout:180];(nwr["power"="substation"]["name"]({b});nwr["power"="plant"]["name"]({b}););out center tags;'
CACHE = ROOT / "data/layers/osm_tiles"


def fetch(i, bbox):
    path = CACHE / f"{i}.json"
    if path.exists():
        return json.loads(path.read_text())
    b = ",".join(map(str, bbox))
    for attempt in range(12):
        url = MIRRORS[(i + attempt) % len(MIRRORS)]  # spread tiles across mirrors
        try:
            r = httpx.post(url, data={"data": QUERY.format(b=b)}, timeout=200, headers={"User-Agent": "opencrew/0.1 (hackathon)"})
            if r.headers.get("content-type", "").startswith("application/json"):
                els = r.json()["elements"]
                path.write_text(json.dumps(els))
                print("tile", i, len(els), url, flush=True)
                return els
            print("busy", i, url, flush=True)
        except httpx.HTTPError as e:
            print("error", i, url, e, flush=True)
        time.sleep(10 + attempt * 5)
    raise RuntimeError(f"overpass failed for {bbox}")


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        tiles = list(pool.map(lambda t: fetch(*t), enumerate(TILES)))
    seen, out = set(), []
    for el in (el for els in tiles for el in els):
        key = (el["type"], el["id"])
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if key in seen or lat is None:
            continue
        seen.add(key)
        out.append({"osm": f"{el['type']}/{el['id']}", "lat": lat, "lon": lon, **{k: el["tags"].get(k) for k in ("name", "operator", "power", "voltage")}})
    path = ROOT / "data/layers/osm_substations.json"
    path.write_text(json.dumps(out))
    print("saved", len(out), path)


if __name__ == "__main__":
    main()
