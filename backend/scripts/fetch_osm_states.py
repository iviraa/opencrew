"""Named OSM substations and plants for each US state, one cached Overpass query per state."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.db import ROOT
import os

from scripts.fetch_osm import MIRRORS as BASE

MIRRORS = os.environ.get("OVERPASS_MIRRORS", "").split(",") if os.environ.get("OVERPASS_MIRRORS") else BASE

STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
          "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
          "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]
QUERY = ('[out:json][timeout:600];area["ISO3166-2"="US-{st}"][admin_level=4]->.s;'
         '(nwr["power"="substation"]["name"](area.s);nwr["power"="plant"]["name"](area.s););out center tags;')
CACHE = ROOT / "data/layers/osm_states"


def fetch(i, st):
    path = CACHE / f"{st}.json"
    if path.exists():
        return st, len(json.loads(path.read_text()))
    for attempt in range(10):
        url = MIRRORS[(i + attempt) % len(MIRRORS)]
        try:
            r = httpx.post(url, data={"data": QUERY.format(st=st)}, timeout=700, headers={"User-Agent": "opencrew/0.1 (hackathon)"})
            if r.headers.get("content-type", "").startswith("application/json"):
                out = []
                for el in r.json()["elements"]:
                    lat = el.get("lat") or el.get("center", {}).get("lat")
                    lon = el.get("lon") or el.get("center", {}).get("lon")
                    if lat is not None:
                        out.append({"osm": f"{el['type']}/{el['id']}", "lat": lat, "lon": lon, "state": st,
                                    **{k: el["tags"].get(k) for k in ("name", "operator", "power", "voltage")}})
                path.write_text(json.dumps(out))
                print(st, len(out), url, flush=True)
                return st, len(out)
            print("busy", st, url, flush=True)
        except httpx.HTTPError as e:
            print("error", st, url, e, flush=True)
        time.sleep(15 + attempt * 10)
    print("failed", st, flush=True)
    return st, None


def main(states):
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(2) as pool:  # public overpass servers: stay polite
        for st, n in pool.map(lambda t: fetch(*t), enumerate(states)):
            pass
    print("done", sorted(p.stem for p in CACHE.glob("*.json")))


if __name__ == "__main__":
    todo = sys.argv[1:] or [s for s in STATES if s not in ("GA", "SC")]
    main(todo[::-1] if os.environ.get("REVERSE") else todo)
