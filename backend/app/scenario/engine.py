"""The scenario overlay: one Scenario dict holds every change; apply it inside a transaction, evaluate, roll back.

Scenario = {jobs: {job_id: {start, end, in_service, cancelled}}, new_jobs: [...], assumptions: {key: {low, high}},
            exclude_partners: [org_id], constraints: {blackout_months: {job_id|"*": [months]}, max_slip_months},
            budget: {cap_usd, target_savings_usd}, capacity: {crews_extra, quarter}, event: {...}}
"""
import calendar
import hashlib
import json
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from app.config import ASSUMPTIONS
from app.engine.overlap import recompute
from app.hazards import cost as hcost
from app.planner import build as planner

EMPTY = {"jobs": {}, "new_jobs": [], "assumptions": {}, "exclude_partners": [], "constraints": {}, "budget": None, "capacity": None, "event": None}
KEYS = tuple(EMPTY)
JOB_SQL = "SELECT id, org_id, name, state, lower(work_window)::date AS start_at, upper(work_window)::date AS end_at, in_service FROM job WHERE id = %s"
NEW_JOB_SQL = """
INSERT INTO job (id, org_id, name, horizon, job_type, voltage_kv, endpoints, geom, geom_quality, work_window, window_basis, in_service, extraction,
                 confidence, resources, state, planner, status, raw)
VALUES (%(id)s, %(org_id)s, %(name)s, 'long', %(job_type)s, %(kv)s, %(ends)s, ST_GeogFromText(%(wkt)s), 'what_if',
        tstzrange(%(start)s, %(in_service)s), 'filed', %(in_service)s, 'manual', 0.5, ARRAY['crews', 'row', 'staging'], %(state)s, 'what-if',
        'hypothetical', %(raw)s)
"""


def empty():
    return json.loads(json.dumps(EMPTY))


def merge(base, change):
    """Later changes win on the same key; jobs, assumptions and constraints merge per entry, lists union, new_jobs append."""
    out = json.loads(json.dumps(base or EMPTY))
    for k in KEYS:
        out.setdefault(k, json.loads(json.dumps(EMPTY[k])))
    for k, v in (change or {}).items():
        if k not in KEYS or v in (None, {}, []):
            continue
        if k in ("jobs", "assumptions"):
            for jid, spec in v.items():
                out[k][jid] = {**out[k].get(jid, {}), **spec}
        elif k == "constraints":
            for ck, cv in v.items():
                if ck == "blackout_months":
                    bl = out[k].setdefault("blackout_months", {})
                    for site, months in cv.items():
                        bl[site] = sorted({int(m) for m in [*bl.get(site, []), *months] if 1 <= int(m) <= 12})
                else:
                    out[k][ck] = cv
        elif k == "exclude_partners":
            out[k] = sorted(set(out[k]) | set(v))
        elif k == "new_jobs":
            out[k] = [*out[k], *v]
        else:
            out[k] = v
    return out


def is_empty(scenario):
    return all(not scenario.get(k) for k in KEYS)


def _d(v):
    if isinstance(v, (datetime, date)):
        return v if isinstance(v, date) and not isinstance(v, datetime) else v.date()
    return date.fromisoformat(str(v)[:10])


def month_add(d, months):
    return d + relativedelta(months=int(months))


def touched_jobs(scenario):
    return sorted(set(scenario.get("jobs", {})) | {j["id"] for j in scenario.get("new_jobs", [])})


def place_new_job(conn, spec, idx):
    """A hypothetical project on the map: from two station names (matched like the loaders do) or explicit coordinates."""
    from app.ingest.national.common import find_station
    org = spec.get("org_id")
    st = conn.execute("SELECT state FROM org WHERE id = %s", (org,)).fetchone()
    if not st:
        raise ValueError(f"unknown utility {org!r}")
    states = [s for s in [spec.get("state"), st["state"]] if s]
    pts = []
    if spec.get("coords"):
        pts = [(float(c[0]), float(c[1])) for c in spec["coords"]][:2]
    else:
        for end in (spec.get("ends") or [])[:2]:
            hit = find_station(end, states)
            if not hit:
                raise ValueError(f"no substation matched {end!r} in {', '.join(states)}; give coords instead")
            pts.append((hit["lon"], hit["lat"]))
    if not pts:
        raise ValueError("a new project needs ends (two station names) or coords")
    wkt = f"LINESTRING({pts[0][0]} {pts[0][1]}, {pts[1][0]} {pts[1][1]})" if len(pts) == 2 else f"POINT({pts[0][0]} {pts[0][1]})"
    start, ins = _d(spec.get("start") or date.today()), _d(spec.get("in_service") or spec.get("end") or (date.today() + relativedelta(years=2)))
    if ins <= start:
        raise ValueError("in_service must be after start")
    jid = f"whatif-{hashlib.sha1(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:8]}-{idx}"
    conn.execute(NEW_JOB_SQL, {"id": jid, "org_id": org, "name": str(spec.get("name") or "Hypothetical project")[:200],
                               "job_type": "new_line" if len(pts) == 2 else "substation", "kv": int(spec["kv"]) if spec.get("kv") else None,
                               "ends": spec.get("ends") or None, "wkt": wkt, "start": start, "in_service": ins, "state": states[0],
                               "raw": json.dumps(spec, default=str)})
    return jid


def apply(conn, scenario):
    """Write the scenario into the open transaction; the caller rolls back. Returns what was touched."""
    touched, notes = [], []
    for jid, spec in scenario.get("jobs", {}).items():
        row = conn.execute(JOB_SQL, (jid,)).fetchone()
        if not row:
            notes.append(f"no project {jid}")
            continue
        if spec.get("cancelled"):
            conn.execute("DELETE FROM opportunity WHERE job_a = %s OR job_b = %s", (jid, jid))
            for t in ("job_hazard", "phase_risk", "job_version"):
                conn.execute(f"DELETE FROM {t} WHERE job_id = %s", (jid,))
            conn.execute("DELETE FROM job WHERE id = %s OR parent_job_id = %s", (jid, jid))
            notes.append(f"{row['name']} cancelled")
            continue
        start = _d(spec.get("start") or row["start_at"])
        end = _d(spec.get("end") or spec.get("in_service") or row["end_at"])
        ins = _d(spec.get("in_service") or (row["in_service"] + (end - row["end_at"]) if row["in_service"] else end))
        if end <= start:
            raise ValueError(f"{row['name']}: the window must end after it starts")
        conn.execute("UPDATE job SET work_window = tstzrange(%s, %s), in_service = %s WHERE id = %s", (start, end, ins, jid))
        conn.execute("DELETE FROM job WHERE parent_job_id = %s", (jid,))  # derived phases no longer match
        touched.append(jid)
    for i, spec in enumerate(scenario.get("new_jobs", [])):
        touched.append(place_new_job(conn, spec, i))
    if scenario.get("exclude_partners"):
        conn.execute("""DELETE FROM opportunity op USING job ja, job jb WHERE ja.id = op.job_a AND jb.id = op.job_b
                        AND (ja.org_id = ANY(%(x)s) OR jb.org_id = ANY(%(x)s))""", {"x": list(scenario["exclude_partners"])})
    if touched:
        recompute(conn, "long", only_jobs=touched)
    return {"touched": touched, "notes": notes}


def assumption_overrides(scenario):
    out = {}
    for k, v in (scenario.get("assumptions") or {}).items():
        if k in ASSUMPTIONS and isinstance(v, dict):
            out[k] = {end: float(v[end]) for end in ("low", "high") if end in v}
    return out


class Context:
    """Assumption and rule overrides the engines read while a scenario is evaluated."""

    def __init__(self, scenario):
        self.overrides = assumption_overrides(scenario)
        self.blackout = (scenario.get("constraints") or {}).get("blackout_months") or None

    def __enter__(self):
        self.t1 = hcost.OVERRIDES.set(self.overrides or None)
        self.t2 = planner.BLACKOUT.set(self.blackout)
        return self

    def __exit__(self, *a):
        hcost.OVERRIDES.reset(self.t1)
        planner.BLACKOUT.reset(self.t2)


def run(conn, company, scenario, evaluate, base_scenario=None):
    """Base then scenario inside one savepoint that is rolled back; returns (base, result, applied). evaluate(conn, scenario, applied)."""
    scenario = merge(EMPTY, scenario)
    base_scenario = merge(EMPTY, base_scenario) if base_scenario else None
    conn.execute("SAVEPOINT what_if")  # everything under here is discarded, whatever happens
    try:
        if base_scenario and not is_empty(base_scenario):
            conn.execute("SAVEPOINT what_if_base")
            applied0 = apply(conn, base_scenario)
            with Context(base_scenario):
                base = evaluate(conn, base_scenario, applied0)
            conn.execute("ROLLBACK TO SAVEPOINT what_if_base")
        else:
            with Context(EMPTY):
                base = evaluate(conn, EMPTY, None)
        applied = apply(conn, scenario)
        with Context(scenario):
            result = evaluate(conn, scenario, applied)
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT what_if")
        conn.execute("RELEASE SAVEPOINT what_if")
    return base, result, applied


def guarded(conn, fn, notes, what):
    """Run an optional evaluation under its own savepoint so a failure cannot poison the transaction."""
    conn.execute("SAVEPOINT what_if_part")
    try:
        return fn()
    except Exception as e:
        conn.execute("ROLLBACK TO SAVEPOINT what_if_part")
        notes.append(f"{what} not computed ({type(e).__name__}: {str(e)[:80]})")
        return None
    finally:
        conn.execute("RELEASE SAVEPOINT what_if_part")


def quarter_range(q):
    """'2027Q2' -> (Apr 1, Jun 30)."""
    y, n = int(str(q)[:4]), int(str(q)[-1])
    m = (n - 1) * 3 + 1
    return date(y, m, 1), date(y, m + 2, calendar.monthrange(y, m + 2)[1])


def months_shift(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


def window_shifted(conn, job_id, months=None, start=None, end=None):
    """A jobs entry that shifts one project's window by months, or sets new dates."""
    row = conn.execute(JOB_SQL, (job_id,)).fetchone()
    if not row:
        raise ValueError(f"no project {job_id}")
    if months is not None:
        return {"start": month_add(row["start_at"], months).isoformat(), "end": month_add(row["end_at"], months).isoformat(),
                "in_service": month_add(row["in_service"] or row["end_at"], months).isoformat()}
    spec = {}
    if start:
        spec["start"] = _d(start).isoformat()
    if end:
        spec["end"] = _d(end).isoformat()
        spec["in_service"] = spec["end"]
    if not spec:
        raise ValueError("give months or new dates")
    return spec


def days_between(a, b):
    return (b - a).days + 1 if b >= a else 0


def fmt_window(start, end):
    return f"{start:%b %Y} to {end:%b %Y}"


def unchanged_row_counts(conn):
    j = conn.execute("SELECT count(*) AS n FROM job").fetchone()["n"]
    o = conn.execute("SELECT count(*) AS n FROM opportunity").fetchone()["n"]
    return {"jobs": j, "opportunities": o}


def month_add_safe(d, months):
    try:
        return month_add(d, months)
    except Exception:
        return d + timedelta(days=30 * int(months))
