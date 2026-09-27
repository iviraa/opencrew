"""apply_event: what one event does to a set of jobs, read as they are in the current transaction (so overlays compose)."""
import calendar
from datetime import date, datetime, timedelta, timezone

from app.config import MAX_DRIVE_MIN, STOP_RULES
from app.engine.cost import SHARE, factors
from app.hazards import cost as hcost
from app.hazards import exposure
from app.hazards.config import HAZARDS
from app.stormlab import wind
from app.stormlab.finding import usd

RECOVERY_DAYS = {64: 3, 50: 2, 34: 1}  # days after the winds pass before aerial work resumes: access, debris, restoration crews (estimate)
MIN_PASSAGE_DAYS = 1
RULES = ["crane_gust_mph", "aerial_lift_wind_mph", "adverse_weather_structures"]  # why a 34 kt (39 mph) wind day is an affected day
ROW_SQL = """
SELECT j.id, j.org_id, j.name, lower(j.work_window) AS start_at, upper(j.work_window) AS end_at,
       ST_X(ST_PointOnSurface(j.geom::geometry)) AS lon, ST_Y(ST_PointOnSurface(j.geom::geometry)) AS lat,
       ST_Buffer(j.geom, 2000)::geometry AS footprint
FROM job j WHERE j.id = ANY(%(ids)s)
"""
PAIRS_SQL = """
SELECT op.id, op.job_a, op.job_b, op.drive_min FROM opportunity op
WHERE op.horizon = 'long' AND (op.job_a = ANY(%(ids)s) OR op.job_b = ANY(%(ids)s)) AND op.drive_min IS NOT NULL AND op.drive_min <= %(max)s
"""


def _day(d):
    return d.date() if isinstance(d, datetime) else d


def rows_for(conn, jobs_in_scope):
    """Job rows with windows, points and footprints: what the caller passed, filled in from the transaction where missing."""
    rows = {}
    for j in jobs_in_scope or []:
        r = dict(j)
        if "start_at" not in r and r.get("work_window") is not None:
            r["start_at"], r["end_at"] = r["work_window"].lower, r["work_window"].upper
        rows[r["id"]] = r
    need = [i for i, r in rows.items() if "lon" not in r or "start_at" not in r or "footprint" not in r]
    if need:
        for db in conn.execute(ROW_SQL, {"ids": need}).fetchall():
            base = rows[db["id"]]
            for k, v in db.items():
                base.setdefault(k, v)  # the caller's window wins over the table's
    return [r for r in rows.values() if r.get("lon") is not None and r.get("start_at") is not None]


def covers(r, when):
    return _day(r["start_at"]) <= when <= _day(r["end_at"])


def site_days(band, hours):
    """Affected days a band gives a site: the passage plus a recovery allowance, low and high."""
    passage = max(MIN_PASSAGE_DAYS, -(-hours // 24))
    rec = RECOVERY_DAYS[band]
    return {"low": float(passage + rec // 2), "high": float(passage + rec)}


def site_cost(r, days, when):
    """What those days cost this site, from the shared cost model (idle crew and equipment, storm-rate labor after the event)."""
    mix, inside = hcost.phase_mix((r["start_at"], r["end_at"]), when - timedelta(days=1), when + timedelta(days=int(days["high"])))
    item = hcost.hazard_item("tropical", days, mix)
    return item["total"], {end: hcost.per_day(mix, end)["standby"] for end in hcost.ENDS}, inside


def storm_event(conn, company, wf, when, rows):
    """Exposure of the rows to a wind field on a date: bands, days, cost, neighbors outside the field, coordination on shared days."""
    active = [r for r in rows if covers(r, when)]
    hit = {}
    for r in active:
        band, hours = wind.band_of(wf, r["lon"], r["lat"])
        if band:
            days = site_days(band, hours)
            total, per_day, inside = site_cost(r, days, when)
            hit[r["id"]] = {**{k: r[k] for k in ("id", "org_id", "name")}, "band_kt": band, "hours_in_winds": hours, "days": days, "cost": total,
                            "per_day": per_day, "inside_window": inside}
    ours = [h for h in hit.values() if h["org_id"] == company]
    theirs = [h for h in hit.values() if h["org_id"] != company]
    # neighbors: partner sites within a crew's drive of an exposed site of ours, active, and outside the 34 kt field
    by_id = {r["id"]: r for r in rows}
    capacity, shared = [], {"low": 0.0, "high": 0.0}
    our_ids = [h["id"] for h in ours]
    pairs = conn.execute(PAIRS_SQL, {"ids": our_ids, "max": MAX_DRIVE_MIN}).fetchall() if our_ids else []
    for p in pairs:
        mine = p["job_a"] if p["job_a"] in hit and hit[p["job_a"]]["org_id"] == company else p["job_b"]
        other = p["job_b"] if mine == p["job_a"] else p["job_a"]
        o = by_id.get(other)
        if not o or o["org_id"] == company or not covers(o, when):
            continue
        if other in hit:  # both exposed: one standby crew and yard on the days they share
            a, b = hit[mine], hit[other]
            small = min(a, b, key=lambda h: h["per_day"]["high"])
            for end in hcost.ENDS:
                shared[end] += min(a["days"][end], b["days"][end]) * factors(None, p["drive_min"])["drive"] * SHARE[end] * small["per_day"][end]
        else:
            capacity.append({"partner": o["org_id"], "project": o["name"], "job_id": other, "drive_min": p["drive_min"], "for": hit[mine]["name"]})
    capacity.sort(key=lambda c: c["drive_min"])
    seen, cap = set(), []
    for c in capacity:
        if c["job_id"] not in seen:
            seen.add(c["job_id"])
            cap.append(c)
    total = {end: round(sum(h["cost"][end] for h in ours), -2) for end in hcost.ENDS}
    days = {end: round(sum(h["days"][end] for h in ours), 1) for end in hcost.ENDS}
    m = {"affected_days_low": days["low"], "affected_days_high": days["high"], "weather_cost_low": total["low"], "weather_cost_high": total["high"],
         "exposed_sites": len(ours), "exposed_projects": len(hit), "neighbors_with_capacity": len(cap),
         "savings_low": round(min(shared["low"], total["low"]), -2), "savings_high": round(min(shared["high"], total["high"]), -2)}
    bands = {kt: sum(1 for h in ours if h["band_kt"] == kt) for kt in (64, 50, 34)}
    evidence = [f"{len(ours)} of our {len([r for r in active if r['org_id'] == company])} active sites sit in the wind field: "
                f"{bands[64]} in hurricane-force winds, {bands[50]} in 50 kt winds, {bands[34]} in tropical-storm winds",
                f"{len(theirs)} neighbor sites are exposed too" if theirs else "no neighbor site in scope is exposed",
                f"affected days {days['low']:g} to {days['high']:g} across our exposed sites, costing {usd(total['low'])} to {usd(total['high'])}"]
    if cap:
        evidence.append("capacity available nearby: " + "; ".join(f"{c['project']} ({c['partner']}, {c['drive_min']:.0f} min from {c['for']})" for c in cap[:3]))
    if shared["high"] > 0:
        evidence.append(f"one standby crew and yard on shared days would save {usd(m['savings_low'])} to {usd(m['savings_high'])}")
    rules = [f"{k}: {STOP_RULES[k]['threshold']} {STOP_RULES[k]['unit']}" for k in RULES if k in STOP_RULES]
    notes = ["Affected days = the days a site spends inside 34 kt (39 mph) winds, which stop crane and aerial work (" + "; ".join(rules) + "), "
             "plus a recovery allowance of 1, 2 or 3 days by wind band (estimate).",
             "Costs use the shared cost model: idle crew and equipment on standby or a demobilize-and-return, plus storm-rate labor. Estimates for assessment, never work orders."]
    return {"metrics": m, "evidence": evidence, "notes": notes, "sites": sorted(hit.values(), key=lambda h: (-h["band_kt"], -h["cost"]["high"])),
            "capacity": cap[:10], "bands_count": bands}


def year_event(conn, company, year, rows, hazards=None):
    """One real year's county event-days applied to the rows' own windows: affected days and cost per hazard."""
    from app.stormlab import replay
    hazards = hazards or list(HAZARDS)
    replay.ensure_events(conn)
    per_site, m = [], {"affected_days_low": 0.0, "affected_days_high": 0.0, "weather_cost_low": 0.0, "weather_cost_high": 0.0}
    for r in rows:
        if r["org_id"] != company:
            continue
        fips = exposure.county_fips_for(conn, r["footprint"])
        if not fips:
            continue
        shares = exposure.month_shares(_day(r["start_at"]), _day(r["end_at"]))
        ev = conn.execute(replay.YEAR_SQL, {"fips": fips, "year": year, "hazards": hazards}).fetchall()
        days = replay.year_days(ev, shares, fips)
        mix, _ = hcost.phase_mix((r["start_at"], r["end_at"]), _day(r["start_at"]), _day(r["end_at"]))
        items = [hcost.hazard_item(h, d, mix) for h, d in days.items() if d["high"] > 0]
        site = {"id": r["id"], "name": r["name"], "days": {e: round(sum(d[e] for d in days.values()), 1) for e in hcost.ENDS},
                "cost": {e: round(sum(i["total"][e] for i in items), -2) for e in hcost.ENDS}, "by_hazard": days}
        per_site.append(site)
        for e in hcost.ENDS:
            m[f"affected_days_{e}"] += site["days"][e]
            m[f"weather_cost_{e}"] += site["cost"][e]
    m = {k: round(v, 1) if "days" in k else round(v, -2) for k, v in m.items()}
    lead = {}
    for s in per_site:
        for h, d in s["by_hazard"].items():
            lead[h] = lead.get(h, 0.0) + d["high"]
    top = sorted(lead.items(), key=lambda kv: -kv[1])[:3]
    evidence = [f"{year}: {m['affected_days_low']:g} to {m['affected_days_high']:g} affected days across {len(per_site)} of our sites, "
                f"costing {usd(m['weather_cost_low'])} to {usd(m['weather_cost_high'])}"]
    if top:
        evidence.append("led by " + ", ".join(f"{HAZARDS[h][0]} ({v:.1f} d)" for h, v in top))
    notes = [f"Event-days come from NOAA Storm Events for {year} in the counties under each site, scaled to the months each build window covers; "
             "low and high are the least and most exposed county. Estimates for assessment, never work orders."]
    return {"metrics": m, "evidence": evidence, "notes": notes, "sites": per_site}


def apply_event(conn, company, event, jobs_in_scope):
    """{metrics, evidence, notes, ...} for an event over these job rows. event: {kind: storm|historical|year, ...}."""
    rows = rows_for(conn, jobs_in_scope)
    kind = event.get("kind")
    if kind == "year":
        return year_event(conn, company, int(event["year"]), rows, event.get("hazards"))
    if kind == "historical":
        from app.storm import helene
        wf = wind.helene_field()
        if not wf:
            return {"metrics": {}, "evidence": [], "notes": ["No Helene advisory data on this machine."]}
        out = storm_event(conn, company, wf, helene.LANDFALL.date(), rows)
        out["storm"] = {"name": "Helene", "date": helene.LANDFALL.date().isoformat(), "advisory": wf["advisory"], "radii_source": wf["radii_source"]}
        return out
    if kind == "storm":
        when = event["date"] if isinstance(event["date"], date) else date.fromisoformat(str(event["date"])[:10])
        cat, note = event.get("category"), None
        if cat is None and event.get("max_wind_mph"):
            cat = wind.category_of(float(event["max_wind_mph"]))
        cat, note = wind.parse_category(cat)
        tornado = cat in wind.TORNADO_MPH
        landfall = datetime.combine(when, datetime.min.time(), timezone.utc) + timedelta(hours=12)
        wf = wind.field(float(event["lon"]), float(event["lat"]), landfall, cat, float(event.get("heading_deg", 20.0)),
                        0.0 if tornado else float(event.get("speed_mph", wind.FORWARD_MPH)))  # a tornado is modeled where it touches down, not as a moving cyclone
        out = storm_event(conn, company, wf, when, rows)
        if note:
            out.setdefault("notes", []).append(note)
        if tornado:
            out.setdefault("notes", []).append(f"{cat} tornado modeled as a narrow wind field about a mile wide at that point; real paths vary")
        out["storm"] = {"category": cat, "max_wind_mph": wind.wind_of(cat), "date": when.isoformat(), "lon": event["lon"], "lat": event["lat"],
                        "heading_deg": wf["heading_deg"], "speed_mph": wf["speed_mph"], "radii_nm": wf["radii_nm"], "place": event.get("place")}
        return out
    raise ValueError(f"unknown event kind {kind!r}")
