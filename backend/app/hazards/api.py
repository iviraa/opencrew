"""Hazard map endpoints: layers per period, exposure per site or zone, and a refresh."""
import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import current_user
from app.db import get_conn
from app.hazards import cost as hazard_cost, exposure, layers
from app.hazards.config import CACHE, HAZARDS, SOURCES
from app.hazards.exposure import PERIODS, PRODUCTS, period_range

router = APIRouter(prefix="/api/app/hazards")

LAYERS_SQL = """
SELECT id, layer, hazard, product, label, rank, period_start, period_end, props, source, fetched_at, ST_AsGeoJSON(geom::geometry, 4)::json AS geometry
FROM hazard_layer
WHERE hazard = ANY(%(hazards)s) AND product = ANY(%(products)s) AND period_end >= %(start)s AND period_start <= %(end)s
  AND (%(bbox)s::text IS NULL OR ST_Intersects(geom::geometry, ST_MakeEnvelope(%(x0)s, %(y0)s, %(x1)s, %(y1)s, 4326)))
ORDER BY rank, period_start
"""
CLIMATE_SQL = "SELECT county_fips, hazard, event_days, years, damage_usd FROM hazard_climate WHERE month = %(m)s AND hazard = ANY(%(hazards)s)"
NRI_SQL = "SELECT county_fips, scores FROM hazard_nri"


def parse_hazards(s):
    picked = [h for h in (s or "").split(",") if h in HAZARDS] or list(HAZARDS)
    return picked


def parse_bbox(s):
    try:
        x0, y0, x1, y1 = [float(v) for v in s.split(",")]
        return x0, y0, x1, y1
    except (AttributeError, ValueError):
        return None


def feature(r):
    props = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items() if k != "geometry"}
    return {"type": "Feature", "id": r["id"], "geometry": r["geometry"], "properties": props}


def climate_counties(conn, month, hazards, bbox):
    """County polygons carrying that month's event-days per hazard (and FEMA scores), from the cached simplified county file."""
    path = CACHE / "counties.geojson"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        from shapely.geometry import mapping
        feats = [{"type": "Feature", "id": f, "geometry": mapping(g.simplify(0.02, preserve_topology=True)), "properties": {"fips": f}}
                 for f, g in layers.county_shapes().items()]
        path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    counties = json.loads(path.read_text())
    days = {}
    for r in conn.execute(CLIMATE_SQL, {"m": month, "hazards": hazards}).fetchall():
        days.setdefault(r["county_fips"], {})[r["hazard"]] = round(r["event_days"] / max(r["years"], 1), 1)  # days per year in that month
    nri = {r["county_fips"]: r["scores"] for r in conn.execute(NRI_SQL).fetchall()}
    out = []
    for f in counties["features"]:
        fips = f["properties"]["fips"]
        if bbox and not layers.county_shapes()[fips].intersects(layers.Polygon.from_bounds(*bbox)):
            continue
        d = days.get(fips, {})
        if not d:
            continue
        out.append({**f, "properties": {"fips": fips, "days": d, "total": round(sum(d.values()), 1),
                                        "nri": {h: v for h, v in (nri.get(fips) or {}).items() if h in hazards}}})
    return {"type": "FeatureCollection", "features": out}


@router.get("/layers")
def hazard_layers(period: str = "now7", month: int | None = None, hazards: str | None = None, bbox: str | None = None,
                  user=Depends(current_user), conn=Depends(get_conn)):
    if period not in PERIODS:
        raise HTTPException(400, f"period must be one of {PERIODS}")
    picked, box = parse_hazards(hazards), parse_bbox(bbox)
    fetched = {r["product"]: r["fetched_at"].isoformat() for r in conn.execute("SELECT product, fetched_at FROM hazard_fetch").fetchall()}
    if period == "month":
        m = month or date.today().month
        return {"period": period, "month": m, "layers": {"climate": climate_counties(conn, m, picked, box)}, "fetched": fetched,
                "sources": [SOURCES["storm_events"], SOURCES["nri"], SOURCES["counties"]]}
    start, end = period_range(period, month)
    rows = conn.execute(LAYERS_SQL, {"hazards": picked, "products": PRODUCTS.get(period, PRODUCTS["now7"]),
                                     "start": datetime.combine(start, datetime.min.time(), timezone.utc),
                                     "end": datetime.combine(end, datetime.max.time(), timezone.utc), "bbox": ",".join(map(str, box)) if box else None,
                                     **dict(zip(("x0", "y0", "x1", "y1"), box or (0, 0, 0, 0)))}).fetchall()
    by = {"alerts": [], "outlooks": [], "fires": [], "quakes": []}
    for r in rows:
        by[r["layer"]].append(feature(r))
    used = {r["source"] for r in rows}
    return {"period": period, "start": start.isoformat(), "end": end.isoformat(),
            "layers": {k: {"type": "FeatureCollection", "features": v} for k, v in by.items()}, "fetched": fetched,
            "sources": [SOURCES[s] for s in SOURCES if s in used]}


@router.get("/exposure")
def hazard_exposure(kind: str, id: str, period: str = "now7", month: int | None = None, hazards: str | None = None, cost: bool = False,
                    user=Depends(current_user), conn=Depends(get_conn)):
    if kind not in ("site", "zone") or period not in PERIODS:
        raise HTTPException(400, "kind must be site or zone; period one of " + ", ".join(PERIODS))
    picked = parse_hazards(hazards)
    out = exposure.assess(conn, kind, id, period, month, picked)
    if not out:
        raise HTTPException(404, f"{kind} {id} not found")
    if cost:  # expected extra cost of the affected days, and for a pair what coordinating saves
        if kind == "site":
            out["cost"] = hazard_cost.for_site(conn, id, period, month, picked)
        else:
            out["cost"], out["coordination"] = hazard_cost.for_zone(conn, id, period, month, picked)
    return out


@router.post("/refresh")
def hazard_refresh(force: bool = False, user=Depends(current_user), conn=Depends(get_conn)):
    return layers.refresh(conn, force=force)


@router.get("/status")
def hazard_status(user=Depends(current_user), conn=Depends(get_conn)):
    fetched = conn.execute("SELECT product, fetched_at, rows FROM hazard_fetch ORDER BY product").fetchall()
    climate = conn.execute("SELECT count(DISTINCT county_fips) AS counties, max(years) AS years FROM hazard_climate").fetchone()
    return {"fetched": fetched, "climate": climate, "hazards": {k: v[0] for k, v in HAZARDS.items()},
            "stale": {g: layers.stale(conn, g) for g in layers.GROUPS}, "now": datetime.now(timezone.utc).isoformat()}
