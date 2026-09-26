import json
import math
import os
import time

import httpx

from app.db import ROOT

OSRM = os.environ.get("OSRM_URL", "https://router.project-osrm.org")  # public demo server; set OSRM_URL for a self-hosted one
CACHE = ROOT / "data/layers/drive_cache.json"
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)"}
BEARINGS = 16
RADII_KM = [8, 16, 24, 32, 44, 56]


class Drive:
    def __init__(self):
        self.cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
        self.last, self.failures = 0.0, 0

    def _get(self, url, params):
        if self.failures >= 3:
            return None  # server down: stop trying this run
        time.sleep(max(0.0, 1.0 - (time.time() - self.last)))  # demo server allows about 1 request per second
        self.last = time.time()
        try:
            r = httpx.get(url, params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            self.failures = 0
            return r.json()
        except (httpx.HTTPError, ValueError):
            self.failures += 1
            return None

    def between(self, a, b):
        """a, b are (lon, lat); returns {"min", "km"} by road or None."""
        key = ";".join(sorted(f"{p[0]:.4f},{p[1]:.4f}" for p in (a, b)))  # symmetric, ~10 m precision
        if key not in self.cache:
            data = self._get(f"{OSRM}/route/v1/driving/{key}", {"overview": "false"})
            if not data or not data.get("routes"):
                return None  # not cached, try again next run
            r = data["routes"][0]
            self.cache[key] = {"min": round(r["duration"] / 60, 1), "km": round(r["distance"] / 1000, 1)}
        return self.cache[key]

    def halfway(self, a, b):
        """Point on the road route at half the drive time, with the road name: a place both crews reach equally fast."""
        key = "half:" + ";".join(f"{p[0]:.4f},{p[1]:.4f}" for p in (a, b))
        if key not in self.cache:
            data = self._get(f"{OSRM}/route/v1/driving/{a[0]:.5f},{a[1]:.5f};{b[0]:.5f},{b[1]:.5f}",
                             {"overview": "false", "steps": "true", "geometries": "geojson"})
            if not data or not data.get("routes"):
                return None
            steps = [st for leg in data["routes"][0]["legs"] for st in leg["steps"]]
            total = sum(st["duration"] for st in steps) or 1.0
            spent, pick, frac = 0.0, steps[-1], 1.0
            for st in steps:
                if st["duration"] > 0 and spent + st["duration"] >= total / 2:
                    pick, frac = st, (total / 2 - spent) / st["duration"]
                    break
                spent += st["duration"]
            coords = pick["geometry"]["coordinates"]
            lon, lat = coords[min(len(coords) - 1, int(frac * (len(coords) - 1)))]  # position within the step by share of its time
            self.cache[key] = {"lon": lon, "lat": lat, "road": pick.get("ref") or pick.get("name") or "", "min": round(total / 120, 1)}
        return self.cache[key]

    def zone(self, center, minutes=45):
        """Approximate drive-time polygon: farthest sampled point per bearing reachable within `minutes`."""
        key = f"zone:{center[0]:.3f},{center[1]:.3f}:{minutes}"
        if key not in self.cache:
            pts = [ring(center, b * 360 / BEARINGS, r) for b in range(BEARINGS) for r in RADII_KM]
            coords = ";".join(f"{x:.5f},{y:.5f}" for x, y in [center, *pts])
            data = self._get(f"{OSRM}/table/v1/driving/{coords}", {"sources": "0"})
            if not data or "durations" not in data:
                return None
            secs = data["durations"][0][1:]
            snap = [d.get("distance", 0) for d in data.get("destinations", [])[1:]]  # metres moved to reach a road
            poly = []
            for b in range(BEARINGS):
                idx = [b * len(RADII_KM) + i for i in range(len(RADII_KM))]
                ok = [pts[i] for i in idx if snap[i] <= 2000 and (secs[i] or 1e9) <= minutes * 60]  # skip samples in swamp or water
                poly.append(ok[-1] if ok else ring(center, b * 360 / BEARINGS, 2))
            self.cache[key] = poly + [poly[0]]
        return self.cache[key]

    def save(self):
        CACHE.write_text(json.dumps(self.cache))


def ring(center, bearing_deg, km):
    lat = math.radians(center[1])
    dx, dy = km * math.sin(math.radians(bearing_deg)), km * math.cos(math.radians(bearing_deg))
    return center[0] + dx / (111.32 * math.cos(lat)), center[1] + dy / 110.57
