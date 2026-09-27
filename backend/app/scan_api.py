"""One round trip for the discovery scan: our projects, the neighbors we overlap with, other utilities nearby, and our overlaps."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.app_api import features
from app.auth import current_user
from app.companies import partner
from app.crewly.app_tools import mine_sql
from app.db import get_conn
from app.queries import JOB_SQL

router = APIRouter(prefix="/api/app")

OTHERS_SQL = """
SELECT j.id, j.org_id, o.name AS org_name, o.color, j.name, j.voltage_kv, j.geom_quality, j.in_service,
       ST_AsGeoJSON(ST_Simplify(j.geom::geometry, 0.002), 5)::json AS geometry,
       ST_Distance(j.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography) / 1000 AS distance_km
FROM job j JOIN org o ON o.id = j.org_id
WHERE j.horizon = 'long' AND j.org_id <> %(me)s AND NOT (j.id = ANY(%(skip)s))
  AND ST_DWithin(j.geom, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography, %(radius_m)s)
ORDER BY distance_km LIMIT %(cap)s
"""


@router.get("/scan_context")
def scan_context(center: str | None = Query(None, pattern=r"^-?\d+(\.\d+)?,-?\d+(\.\d+)?$"), radius_km: float = Query(400, ge=10, le=3000),
                 user=Depends(current_user), conn=Depends(get_conn)):
    me = user["company"]
    ours = conn.execute(JOB_SQL + " WHERE j.horizon = 'long' AND j.org_id = %s ORDER BY lower(j.work_window)", (me,)).fetchall()
    if center:
        lon, lat = (float(x) for x in center.split(","))
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise HTTPException(400, "center must be lon,lat in degrees")
    else:  # the middle of our own service area
        c = conn.execute("SELECT ST_X(ST_Centroid(ST_Collect(geom::geometry))) AS lon, ST_Y(ST_Centroid(ST_Collect(geom::geometry))) AS lat "
                         "FROM job WHERE horizon = 'long' AND org_id = %s", (me,)).fetchone()
        lon, lat = (c["lon"], c["lat"]) if c and c["lon"] is not None else (-82.0, 33.0)
    opps = conn.execute(mine_sql(me) + " ORDER BY op.score DESC, op.distance_m").fetchall()
    for o in opps:
        o["partner"] = partner(o, me)
    partner_ids = sorted({o["job_a"] for o in opps} | {o["job_b"] for o in opps} - {j["id"] for j in ours})
    partners = conn.execute(JOB_SQL + " WHERE j.id = ANY(%s)", (partner_ids,)).fetchall() if partner_ids else []
    others = conn.execute(OTHERS_SQL, {"lon": lon, "lat": lat, "me": me, "skip": partner_ids, "radius_m": radius_km * 1000, "cap": 1500}).fetchall()
    return {"center": [lon, lat], "radius_km": radius_km, "ours": features(ours), "partners": features(partners), "others": features(others),
            "overlaps": opps}
