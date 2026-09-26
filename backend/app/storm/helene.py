import csv
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timedelta, timezone

import httpx
import shapefile
from shapely.geometry import shape

from app.db import ROOT

RAW = ROOT / "data/raw/helene"
logging.getLogger("shapefile").setLevel(logging.ERROR)  # nhc cones use reversed ring order
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)"}
LANDFALL = datetime(2024, 9, 27, 3, 10, tzinfo=timezone.utc)  # Big Bend landfall, 11:10 PM EDT Sep 26
REPLAY = (LANDFALL - timedelta(hours=72), LANDFALL + timedelta(hours=24))
BBOX = (-85.7, 30.3, -78.5, 35.3)  # GA + SC
BEST_TRACK = "https://www.nhc.noaa.gov/gis/best_track/al092024_best_track.zip"
CONE = "https://www.nhc.noaa.gov/gis/forecast/archive/al092024_5day_{n:03d}.zip"
SBW = "https://mesonet.agron.iastate.edu/api/1/vtec/sbw_interval.geojson"
LSR = "https://mesonet.agron.iastate.edu/geojson/lsr.geojson"
DAMAGE = {"TROPICAL CYCLONE", "TORNADO", "TSTM WND DMG", "NON-TSTM WND DMG"}
POWER = re.compile(r"power ?line|utility pole|power pole|transformer|substation|outage", re.I)
SPC = "https://www.spc.noaa.gov/climo/reports/{d}_rpts_filtered_{kind}.csv"
TZ = {"EDT": -4, "EST": -5, "CDT": -5, "AST": -4}


def fetch(url, name):
    path = RAW / name
    if not path.exists():
        r = httpx.get(url, headers=HEADERS, timeout=120, follow_redirects=True)
        if r.status_code != 200:
            return None
        path.write_bytes(r.content)
    return path


def read_shp(zpath, suffix):
    z = zipfile.ZipFile(zpath)
    base = next((n[:-4] for n in z.namelist() if n.endswith(suffix + ".shp")), None)
    if not base:
        return []
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    return [(rec.as_dict(), shape(s.__geo_interface__)) for rec, s in zip(r.records(), r.shapes())]


def adv_time(text):
    m = re.match(r"(\d{1,2})(\d{2}) (AM|PM) (\w{3}) \w{3} (\w{3}) (\d{1,2}) (\d{4})", text)  # "500 AM EDT Fri Sep 27 2024"
    h, mi, ap, tz, mon, day, year = m.groups()
    local = datetime.strptime(f"{year} {mon} {day} {int(h) % 12 + (12 if ap == 'PM' else 0)}:{mi}", "%Y %b %d %H:%M")
    return (local - timedelta(hours=TZ[tz])).replace(tzinfo=timezone.utc)


def track_events():
    z = fetch(BEST_TRACK, "best_track.zip")
    for rec, geom in read_shp(z, "_pts"):
        ts = datetime.strptime(str(rec["DTG"]), "%Y%m%d%H").replace(tzinfo=timezone.utc)
        yield ts, "nhc_track", geom.wkt, {"type": rec["STORMTYPE"], "wind_kt": rec["INTENSITY"], "pressure_mb": rec["MSLP"]}
    for rec, geom in read_shp(z, "_windswath"):
        yield LANDFALL, "nhc_windswath", geom.wkt, {"radius_kt": rec.get("RADII")}


def cone_events():
    for n in range(1, 30):
        z = fetch(CONE.format(n=n), f"cone_{n:03d}.zip")
        if not z:
            continue
        for rec, geom in read_shp(z, "_5day_pgn"):
            yield adv_time(rec["ADVDATE"]), "nhc_cone", geom.wkt, {"advisory": rec["ADVISNUM"], "issued": rec["ADVDATE"], "type": rec["STORMTYPE"]}


def warning_events():
    path = fetch(f"{SBW}?begints={REPLAY[0]:%Y-%m-%dT%H:%MZ}&endts={REPLAY[1]:%Y-%m-%dT%H:%MZ}", "sbw.geojson")
    for f in json.loads(path.read_text())["features"]:
        p, geom = f["properties"], shape(f["geometry"])
        x0, y0, x1, y1 = geom.bounds
        if p["phenomena"] not in ("TO", "SV", "EW", "FF") or x1 < BBOX[0] or x0 > BBOX[2] or y1 < BBOX[1] or y0 > BBOX[3]:
            continue
        ts = datetime.fromisoformat(p["utc_issue"].replace("Z", "+00:00"))
        yield ts, "nws_alert", geom.wkt, {"phenomena": p["phenomena"], "label": p["event_label"], "wfo": p["wfo"],
                                          "expire": p["utc_expire"], "places": p["locations"][:200]}


def spc_events():
    for day in ("240925", "240926", "240927"):
        base = datetime.strptime(day, "%y%m%d").replace(tzinfo=timezone.utc)
        for kind in ("wind", "torn"):
            path = fetch(SPC.format(d=day, kind=kind), f"spc_{day}_{kind}.csv")
            for r in csv.DictReader(io.StringIO(path.read_text(errors="ignore"))):
                if r.get("State") not in ("GA", "SC"):
                    continue
                hhmm = int(r["Time"])
                ts = base + timedelta(days=1 if hhmm < 1200 else 0, hours=hhmm // 100, minutes=hhmm % 100)  # SPC day runs 12Z to 12Z
                yield ts, "spc_report", f"POINT({r['Lon']} {r['Lat']})", {"kind": kind, "place": r["Location"], "county": r["County"],
                                                                         "state": r["State"], "comments": r["Comments"][:300]}


def lsr_events():
    path = fetch(f"{LSR}?sts={REPLAY[0]:%Y-%m-%dT%H:%MZ}&ets={REPLAY[1]:%Y-%m-%dT%H:%MZ}&states=GA,SC", "lsr.geojson")
    for f in json.loads(path.read_text())["features"]:
        p = f["properties"]
        if p["typetext"] not in DAMAGE:
            continue
        ts = datetime.fromisoformat(p["valid"].replace("Z", "+00:00"))
        yield ts, "lsr", f"POINT({p['lon']} {p['lat']})", {"type": p["typetext"], "place": p["city"], "county": p["county"], "state": p["state"],
                                                          "reported_by": p["source"], "remark": (p["remark"] or "")[:300],
                                                          "power": bool(POWER.search(p["remark"] or ""))}
