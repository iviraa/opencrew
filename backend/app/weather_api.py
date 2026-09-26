"""Weather for the Crewly app: a 7-day outlook strip and which of one company's projects sit inside each risk area."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_conn
from app.storm import outlook
from app.storm.outlook import ET, PEAK_HOUR

router = APIRouter(prefix="/api/app")

HELENE_KNOWN = datetime(2024, 9, 25, 12, tzinfo=timezone.utc)  # two days before landfall
KIND = {"spc": "Severe storms", "spc48": "Severe storms", "wpc_ero": "Flash flooding", "nhc_wsp": "Tropical storm winds"}

AT_RISK_SQL = """
SELECT j.id, j.name, j.work_window @> %(view)s::timestamptz AS building
FROM job j JOIN outlook o ON o.id = %(id)s AND o.valid_from = %(vf)s
WHERE j.org_id = %(org)s AND j.horizon = 'long' AND ST_Intersects(j.geom, o.geom)
ORDER BY building DESC, j.name
"""

ALERT_SQL = """
SELECT e.id, e.payload, ST_AsGeoJSON(e.geom, 4)::json AS geometry,
       (SELECT coalesce(json_agg(j.name ORDER BY j.name), '[]') FROM job j
         WHERE j.org_id = %(org)s AND j.horizon = 'long' AND ST_Intersects(j.geom, e.geom)) AS projects
FROM storm_event e
WHERE e.kind = 'nws_alert' AND e.geom IS NOT NULL AND coalesce(e.payload->>'mode', 'replay') = %(mode)s
  AND e.ts <= %(known)s AND (e.payload->>'expire')::timestamptz > %(known)s
"""


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


@router.get("/weather")
def weather(scenario: str = "none", org: str | None = None, conn=Depends(get_conn)):
    if scenario not in ("none", "helene"):
        raise HTTPException(400, "scenario must be none or helene")
    mode = "replay" if scenario == "helene" else "live"
    known = HELENE_KNOWN if scenario == "helene" else datetime.now(timezone.utc)
    days = []
    for i in range(7):
        local = (known.astimezone(ET) + timedelta(days=i)).date()
        view = max(datetime(local.year, local.month, local.day, PEAK_HOUR, tzinfo=ET).astimezone(timezone.utc), known)
        areas = []
        for r in outlook.rows_at(conn, view, known, mode):
            if r["product"] not in KIND:
                continue  # tropical development areas are mostly open ocean; the heads-up list covers them
            projects = conn.execute(AT_RISK_SQL, {"id": r["id"], "vf": r["valid_from"], "view": view, "org": org}).fetchall() if org else []
            props = {k: _iso(v) for k, v in r.items() if k != "geometry"}
            areas.append({"type": "Feature", "geometry": r["geometry"],
                          "properties": {**props, "kind": KIND[r["product"]], "projects": projects}})
        areas.sort(key=lambda f: f["properties"]["rank"] or 0)  # draw worst on top
        at_risk = {p["id"] for a in areas for p in a["properties"]["projects"]}
        days.append({"date": local.isoformat(), "view": view.isoformat(), "label": "Today" if i == 0 else f"{local:%a}",
                     "max_rank": max((a["properties"]["rank"] or 0 for a in areas), default=0), "at_risk": len(at_risk),
                     "areas": {"type": "FeatureCollection", "features": areas}})
    alerts = [{"type": "Feature", "geometry": a["geometry"],
               "properties": {"id": a["id"], "label": a["payload"].get("label"), "headline": a["payload"].get("headline"),
                              "severity": a["payload"].get("severity"), "places": a["payload"].get("places"),
                              "expire": a["payload"].get("expire"), "projects": a["projects"]}}
              for a in conn.execute(ALERT_SQL, {"org": org, "mode": mode, "known": known}).fetchall()]
    return {"scenario": scenario, "known": known.isoformat(), "days": days,
            "alerts": {"type": "FeatureCollection", "features": alerts}, "heads_up": outlook.heads_up(conn, known, mode)}
