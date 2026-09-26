import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.db import ROOT

URL = "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query"  # USFWS NWI
CACHE = ROOT / "data/layers/nwi_cache.json"
PAD_M = 100  # wetland must come within about 100 m of the job


def key(geo):
    return hashlib.sha1(json.dumps(geo, sort_keys=True).encode()).hexdigest()[:16]


def query(geo):
    wkid = {"spatialReference": {"wkid": 4326}}
    if geo["type"] == "LineString":
        geometry, kind = {"paths": [geo["coordinates"]], **wkid}, "esriGeometryPolyline"
    else:
        geometry, kind = {"x": geo["coordinates"][0], "y": geo["coordinates"][1], **wkid}, "esriGeometryPoint"
    r = httpx.post(URL, timeout=30, headers={"User-Agent": "opencrew/0.1 (hackathon)"}, data={
        "geometry": json.dumps(geometry), "geometryType": kind, "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
        "distance": PAD_M, "units": "esriSRUnit_Meter", "returnIdsOnly": "true", "f": "json"})
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise ValueError(data["error"])
    return sorted(str(i) for i in data.get("objectIds") or [])


def lookup(geoms):
    """Wetland ids within PAD_M of each job geometry; jobs the service could not answer map to None."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    keys = {job: key(geo) for job, geo in geoms.items()}
    todo = {keys[job]: geo for job, geo in geoms.items() if keys[job] not in cache}
    fails = [0]  # consecutive failures across threads

    def fetch(item):
        k, geo = item
        for attempt in range(3):
            if fails[0] >= 3:
                return k, None  # service looks down, skip the rest
            try:
                found = query(geo)
                fails[0] = 0
                return k, found
            except (httpx.HTTPError, ValueError):
                time.sleep(0.5 * (attempt + 1))
        fails[0] += 1
        return k, None

    if todo:
        with ThreadPoolExecutor(3) as pool:
            for k, v in pool.map(fetch, todo.items()):
                if v is not None:
                    cache[k] = v
        CACHE.write_text(json.dumps(cache))
    return {job: cache.get(k) for job, k in keys.items()}
