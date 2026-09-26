"""Named substations and plants per state from Geofabrik extracts (same format as fetch_osm_states). Needs pyosmium: pip install osmium."""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import osmium

OUT = Path(__file__).resolve().parents[2] / "data/layers/osm_states"
TMP = OUT.parent / "pbf_tmp"  # extracts are deleted once read
NAMES = {"AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado", "CT": "connecticut",
         "DE": "delaware", "DC": "district-of-columbia", "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho", "IL": "illinois",
         "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
         "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi", "MO": "missouri", "MT": "montana",
         "NE": "nebraska", "NV": "nevada", "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
         "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
         "RI": "rhode-island", "SC": "south-carolina", "SD": "south-dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
         "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west-virginia", "WI": "wisconsin", "WY": "wyoming"}


def extract(st):
    out = OUT / f"{st}.json"
    if out.exists():
        return st, "cached"
    pbf = TMP / f"{st}.osm.pbf"
    if not pbf.exists():
        subprocess.run(["curl", "-sL", "-o", str(pbf) + ".part", f"https://download.geofabrik.de/north-america/us/{NAMES[st]}-latest.osm.pbf"], check=True)
        Path(str(pbf) + ".part").rename(pbf)
    rows = []
    fp = osmium.FileProcessor(str(pbf)).with_locations().with_filter(osmium.filter.KeyFilter("power"))
    for o in fp:
        tags = o.tags
        if tags.get("power") not in ("substation", "plant") or not tags.get("name"):
            continue
        if o.is_node():
            lat, lon = o.location.lat, o.location.lon
        elif o.is_way():
            pts = [(n.location.lat, n.location.lon) for n in o.nodes if n.location.valid()]
            if not pts:
                continue
            lat, lon = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        else:
            continue  # relations are rare for substations; skip
        kind = "node" if o.is_node() else "way"
        rows.append({"osm": f"{kind}/{o.id}", "lat": lat, "lon": lon, "state": st, "name": tags.get("name"), "operator": tags.get("operator"),
                     "power": tags.get("power"), "voltage": tags.get("voltage")})
    if not OUT.joinpath(f"{st}.json").exists():  # the overpass fetch may have finished it meanwhile
        (OUT / f"{st}.json").write_text(json.dumps(rows))
    pbf.unlink()
    return st, len(rows)


if __name__ == "__main__":
    TMP.mkdir(exist_ok=True)
    todo = [s for s in (sys.argv[1:] or NAMES) if not (OUT / f"{s}.json").exists()]
    with ThreadPoolExecutor(6) as pool:
        for st, n in pool.map(extract, todo):
            print(st, n, flush=True)
