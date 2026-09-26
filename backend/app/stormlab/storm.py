"""What-if storm: a named place, a date and a category become a wind field over our sites and our neighbors'."""
import io
import zipfile
from datetime import date, timedelta
from functools import lru_cache

import shapefile
from shapely.geometry import shape

from app.companies import name as org_name
from app.db import ROOT
from app.stormlab import finding, wind
from app.stormlab.events import apply_event

SCOPE_KM = 400  # sites this far from landfall are worth looking at
JOBS_SQL = """
SELECT j.id, j.org_id, j.name, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at,
       ST_X(ST_PointOnSurface(j.geom::geometry)) AS lon, ST_Y(ST_PointOnSurface(j.geom::geometry)) AS lat, ST_Buffer(j.geom, 2000)::geometry AS footprint
FROM job j
WHERE j.horizon = 'long' AND ST_DWithin(j.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(m)s)
  AND j.work_window && tstzrange(%(d0)s::timestamptz, %(d1)s::timestamptz)
"""


@lru_cache
def county_centroids():
    """'charleston' -> [(state, lon, lat)] from the Census county file, for naming a landfall by county."""
    z = zipfile.ZipFile(ROOT / "data/layers/counties_20m.zip")
    base = next(n for n in z.namelist() if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    out = {}
    for rec, s in zip(r.records(), r.shapes()):
        c = shape(s.__geo_interface__).centroid
        out.setdefault(rec["NAME"].lower(), []).append((rec["STUSPS"], c.x, c.y))
    return out


def locate(place, state=None):
    """(lon, lat, label) for a place name: a known region, a county name, else a geocoder lookup."""
    from app.crewly.tools import REGIONS
    key = (place or "").strip().lower()
    if key in REGIONS:
        x0, y0, x1, y1 = REGIONS[key]
        return (x0 + x1) / 2, (y0 + y1) / 2, place.title()
    hits = county_centroids().get(key.replace(" county", ""), [])
    if state:
        hits = [h for h in hits if h[0] == state.upper()] or hits
    if hits:
        st, lon, lat = hits[0]
        return lon, lat, f"{place.title()} County, {st}"
    from app.geo.nominatim import lookup
    hit = lookup(f"{place}, {state}" if state else place)
    if hit:
        return float(hit["lon"]), float(hit["lat"]), hit.get("display_name", place).split(",")[0]
    raise ValueError(f"could not place {place!r}; give a county or city name, or lon and lat")


def jobs_in_scope(conn, lon, lat, when):
    d0, d1 = when - timedelta(days=3), when + timedelta(days=7)
    return conn.execute(JOBS_SQL, {"lon": lon, "lat": lat, "m": SCOPE_KM * 1000, "d0": d0, "d1": d1}).fetchall()


def storm_scenario(conn, company, place=None, lon=None, lat=None, state=None, date_=None, category=None, max_wind_mph=None,
                   historical=None, heading_deg=20.0, speed_mph=wind.FORWARD_MPH):
    """A finding for one storm over our sites: exposure, affected days, cost, neighbors with capacity, coordination on shared days."""
    if historical == "helene":
        from app.storm import helene
        when = helene.LANDFALL.date()
        lon, lat, label = -83.7, 30.1, "Big Bend, FL (Helene, Sep 2024)"
        event = {"kind": "historical", "name": "helene"}
    else:
        when = date_ if isinstance(date_, date) else date.fromisoformat(str(date_ or date.today())[:10])
        if lon is None or lat is None:
            lon, lat, label = locate(place, state)
        else:
            label = place or f"{lat:.2f}, {lon:.2f}"
        cat = category if category in wind.CATEGORY_MPH else (int(category) if str(category or "").isdigit() and int(category) in wind.CATEGORY_MPH else None)
        if cat is None:
            cat = wind.category_of(float(max_wind_mph)) if max_wind_mph else 3
        event = {"kind": "storm", "place": label, "lon": lon, "lat": lat, "date": when, "category": cat, "heading_deg": heading_deg, "speed_mph": speed_mph}
    rows = jobs_in_scope(conn, lon, lat, when)
    out = apply_event(conn, company, event, rows)
    m = out["metrics"]
    if not m:
        raise ValueError(out["notes"][0] if out.get("notes") else "no result")
    base = finding.metrics(affected_days_low=0.0, affected_days_high=0.0, weather_cost_low=0, weather_cost_high=0, exposed_sites=0, exposed_projects=0)
    scenario = finding.metrics(**{k: m[k] for k in m})
    cat_label = "Helene (real track)" if historical == "helene" else (f"Category {event['category']}" if event["category"] != "ts" else "Tropical storm")
    title = f"{cat_label} at {label}, {when:%b %d, %Y}"
    ours_active = len([r for r in rows if r["org_id"] == company])
    knobs = [finding.knob("place", "place", label, "Landfall", lon=lon, lat=lat), finding.knob("date", "date", when.isoformat(), "Date"),
             finding.knob("category", "select", event.get("category", 4), "Category", options=["ts", 1, 2, 3, 4, 5]),
             finding.knob("heading_deg", "number", heading_deg, "Heading (deg)", min=0, max=359)]
    evidence = [f"{ours_active} of our sites are active within {SCOPE_KM} km of landfall on that date"] + out["evidence"]
    sources = [f"{s['title']} ({s['url']})" for s in wind.SOURCES.values()] + ["NHC Hurricane Helene advisories" if historical == "helene" else "crew_costs.json stop rules (OSHA 1926.1417, Genie boom manual, OSHA 1926.964)"]
    f = finding.make("storm_scenario", title, f"What would a {cat_label.lower()} at {label} on {when:%b %d, %Y} do to our active work?",
                     {**{k: (v.isoformat() if isinstance(v, date) else v) for k, v in event.items()}, "company": company},
                     base, scenario, notes=out["notes"], evidence=evidence, knobs=knobs, sources=sources,
                     sites=[{**s, "org": org_name(s["org_id"])} for s in out["sites"][:20]], capacity=out["capacity"], storm=out.get("storm"))
    return finding.save(conn, company, f)
