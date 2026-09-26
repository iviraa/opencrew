import json
import time

import httpx

from app.db import ROOT

MIRRORS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
LATS, LONS = [30.3, 31.6, 32.8, 34.0, 35.3], [-85.7, -83.9, -82.1, -80.3, -78.5]
TILES = [(s, w, n, e) for s, n in zip(LATS, LATS[1:]) for w, e in zip(LONS, LONS[1:])]  # GA + SC in 16 tiles
QUERY = '[out:json][timeout:180];(nwr["power"="substation"]["name"]({b});nwr["power"="plant"]["name"]({b}););out center tags;'


def fetch(bbox):
    b = ",".join(map(str, bbox))
    for attempt in range(12):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            r = httpx.post(url, data={"data": QUERY.format(b=b)}, timeout=120, headers={"User-Agent": "opencrew/0.1 (hackathon)"})
            if r.headers.get("content-type", "").startswith("application/json"):
                return r.json()["elements"]
            print("busy", url)
        except httpx.HTTPError as e:
            print("error", url, e)
        time.sleep(10 + attempt * 5)
    raise RuntimeError(f"overpass failed for {bbox}")


def main():
    seen, out = set(), []
    for bbox in TILES:
        for el in fetch(bbox):
            key = (el["type"], el["id"])
            if key in seen:
                continue
            seen.add(key)
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lon = el.get("lon") or el.get("center", {}).get("lon")
            if lat is not None:
                out.append({"osm": f"{el['type']}/{el['id']}", "lat": lat, "lon": lon, **{k: el["tags"].get(k) for k in ("name", "operator", "power", "voltage")}})
        print("tile done", bbox, len(out))
    path = ROOT / "data/layers/osm_substations.json"
    path.write_text(json.dumps(out))
    print("saved", len(out), path)


if __name__ == "__main__":
    main()
