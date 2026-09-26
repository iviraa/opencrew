from datetime import datetime, timedelta, timezone

from app.storm.helene import LANDFALL

REGION_SQL = "ST_Intersects(i.geom::geometry, ST_MakeEnvelope(%(x0)s, %(y0)s, %(x1)s, %(y1)s, 4326))"
OPP_SQL = "ST_DWithin(i.geom, (SELECT link FROM opportunity WHERE id = %(opp)s), 15000)"  # 15 km around the pair


def when(time=None, hours_from_landfall=None, mode="replay"):
    if hours_from_landfall is not None:
        return LANDFALL + timedelta(hours=float(hours_from_landfall))
    if time:
        t = datetime.fromisoformat(time.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return LANDFALL + timedelta(hours=24) if mode == "replay" else datetime.now(timezone.utc)


def incidents_near(conn, region=None, opportunity_id=None, time=None, hours_from_landfall=None, mode="replay", power_only=False, limit=8):
    from app.crewly.tools import REGIONS
    t = when(time, hours_from_landfall, mode)
    where = ["i.mode = %(mode)s", "i.ts <= %(t)s", "i.ts >= %(t0)s"]
    params = {"mode": mode, "t": t, "t0": t - timedelta(hours=96 if mode == "replay" else 24)}
    box = REGIONS.get((region or "").lower())
    if box:
        where.append(REGION_SQL)
        params.update(zip(("x0", "y0", "x1", "y1"), box))
    if opportunity_id:
        where.append(OPP_SQL)
        params["opp"] = opportunity_id
    if power_only:
        where.append("i.kind IN ('downed_line', 'substation_damage', 'outage', 'tree_on_line')")
    sql = " AND ".join(where)
    stats = conn.execute(f"""SELECT count(*) AS total, count(*) FILTER (WHERE verified) AS verified,
                                    count(*) FILTER (WHERE NOT verified) AS unverified FROM incident i WHERE {sql}""", params).fetchone()
    rows = conn.execute(f"""SELECT i.id, i.ts, i.kind, i.where_text, i.precision, round(i.confidence::numeric, 2) AS confidence, i.verified,
                                   i.customers_affected, i.utility_mentioned, i.nearest,
                                   (SELECT count(*) FROM jsonb_array_elements(i.sources) s WHERE s->>'type' <> 'context') AS sources
                            FROM incident i WHERE {sql} ORDER BY i.verified DESC, i.confidence DESC, i.ts LIMIT %(limit)s""",
                        {**params, "limit": min(limit, 20)}).fetchall()
    out = {"time_utc": t.isoformat(), "mode": mode, "region_known": bool(box) if region else None, **stats,
           "incidents": [{**r, "ts": r["ts"].isoformat(), "confidence": float(r["confidence"])} for r in rows]}
    actions = [{"type": "storm", "at": t.isoformat()}] if mode == "replay" else [{"type": "live"}]
    return out, actions


def weather_alerts(conn):
    rows = conn.execute("""SELECT payload->>'label' AS event, payload->>'severity' AS severity, payload->>'places' AS places,
                                  payload->>'expire' AS expires FROM storm_event
                           WHERE kind = 'nws_alert' AND payload->>'mode' = 'live' AND (payload->>'expire')::timestamptz > now()
                           ORDER BY payload->>'severity', payload->>'label'""").fetchall()
    return {"active_alerts": len(rows), "alerts": rows[:15], "note": "from the last live poll of api.weather.gov"}, [{"type": "live"}]


def phase_weather_risks(conn):
    rows = conn.execute("""SELECT site, day, gust_mph, work, alert, job_id FROM phase_risk ORDER BY day, gust_mph DESC""").fetchall()
    return {"alerts": len(rows), "risks": [{**r, "day": r["day"].isoformat()} for r in rows[:15]],
            "limit_mph": 35, "note": "NWS gridpoint gust forecasts for near-term phases active in the next 7 days"}, [{"type": "view", "horizon": "near", "tier": None, "tab": None}]


INCIDENT_TOOLS = {
    "incidents_near": (incidents_near, "Grid incidents (downed lines, substation damage, outages) merged from NWS/SPC reports and news, with "
                       "confidence, verified status and nearest utility assets. Replay = Hurricane Helene; live = last 24 h.", {
        "region": {"type": "string"}, "opportunity_id": {"type": "integer"}, "time": {"type": "string", "description": "ISO UTC"},
        "hours_from_landfall": {"type": "number"}, "mode": {"type": "string", "enum": ["replay", "live"]},
        "power_only": {"type": "boolean"}, "limit": {"type": "integer"}}, []),
    "weather_alerts": (weather_alerts, "Active NWS alerts for Georgia and South Carolina from the last live poll.", {}, []),
    "phase_weather_risks": (phase_weather_risks, "Near-term construction phases with forecast gusts at or above the crane/line-work limit.", {}, []),
}
