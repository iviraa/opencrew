import csv
import io
import json
import zipfile

import httpx
import shapefile
from shapely.geometry import MultiPolygon, shape

from app.db import ROOT, connect, init_schema

STATES = {"13": ("GA", "Georgia"), "45": ("SC", "SouthCarolina")}
TRACTS = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_{fips}_tract_500k.zip"
STATE_LINES = "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip"
SVI = "https://svi.cdc.gov/Documents/Data/2022/csv/states/{name}.csv"
NRI = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Census_Tracts/FeatureServer/0/query"
LAYERS = ROOT / "data/layers"
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)"}


def download(url, path):
    if not path.exists():
        path.write_bytes(httpx.get(url, headers=HEADERS, timeout=120, follow_redirects=True).raise_for_status().content)
    return path


def state_lines():
    if not (LAYERS / "states/cb_2023_us_state_500k.shp").exists():  # used by the home-state check in geolocation
        zipfile.ZipFile(download(STATE_LINES, LAYERS / "states.zip")).extractall(LAYERS / "states")


def tracts(fips):
    z = zipfile.ZipFile(download(TRACTS.format(fips=fips), LAYERS / f"tracts_{fips}.zip"))
    base = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    for rec, shp in zip(r.records(), r.shapes()):
        g = shape(shp.__geo_interface__)
        yield rec["GEOID"], (g if g.geom_type == "MultiPolygon" else MultiPolygon([g])).wkt


def svi(name):
    text = download(SVI.format(name=name), LAYERS / f"svi_{name}.csv").read_text()
    return {r["FIPS"]: float(r["RPL_THEMES"]) for r in csv.DictReader(io.StringIO(text)) if float(r["RPL_THEMES"]) >= 0}  # -999 = no data


def nri(state):
    out, offset = {}, 0
    while True:
        r = httpx.get(NRI, params={"where": f"STATEABBRV='{state}'", "outFields": "TRACTFIPS,HRCN_RISKS", "returnGeometry": "false",
                                   "resultOffset": offset, "resultRecordCount": 2000, "f": "json"}, headers=HEADERS, timeout=120).json()
        feats = r.get("features", [])
        out.update({f["attributes"]["TRACTFIPS"]: f["attributes"]["HRCN_RISKS"] for f in feats})
        if not r.get("exceededTransferLimit") or not feats:
            return out
        offset += len(feats)


def kv(tag):
    vals = [int(v) // 1000 for v in (tag or "").replace(",", ";").split(";") if v.strip().isdigit()]
    return max(vals) if vals else None


def grid_lines(conn):
    path = LAYERS / "osm_lines.json"
    if not path.exists():
        return 0
    rows = [(w["osm"], kv(w["voltage"]), w["operator"], "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in w["coords"]) + ")")
            for w in json.loads(path.read_text()) if len(w["coords"]) >= 2]
    conn.execute("TRUNCATE grid_line")
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO grid_line VALUES (%s, %s, %s, ST_GeomFromText(%s, 4326)) ON CONFLICT DO NOTHING", rows)
    return len(rows)


def main():
    LAYERS.mkdir(parents=True, exist_ok=True)
    state_lines()
    with connect() as conn:
        init_schema(conn)
        conn.execute("TRUNCATE tract")
        for fips, (abbr, name) in STATES.items():
            vul, risk = svi(name), nri(abbr)
            rows = [(geoid, abbr, wkt, (risk.get(geoid) or 0) / 100, vul.get(geoid)) for geoid, wkt in tracts(fips)]
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO tract VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s, %s)", rows)
            print(abbr, len(rows), "tracts,", len(vul), "svi,", len(risk), "nri")
        print("grid lines", grid_lines(conn))


if __name__ == "__main__":
    main()
