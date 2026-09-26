import json

from dateutil.relativedelta import relativedelta

from app.config import PHASES

DEFAULTS = {"max_delay_months": 2, "max_drive_min": 45, "min_overlap_months": 3}
MONTH_DAYS = 30.44
SEARCH_MONTHS = 240  # give up after 20 years of delay
SLACK = 0.1  # months; three calendar months count as three

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS crew_plan (
  id         SERIAL PRIMARY KEY,
  run_at     TIMESTAMPTZ DEFAULT now(),
  limits     JSONB NOT NULL,
  summary    JSONB NOT NULL,
  decisions  JSONB NOT NULL
)
"""

ROWS_SQL = """
SELECT op.id, op.job_a, op.job_b, op.savings_low, op.savings_high, op.score, {drive} AS drive_min,
       ja.name AS a_name, jb.name AS b_name, ja.org_id AS a_org, jb.org_id AS b_org,
       lower(ja.work_window) AS a_start, upper(ja.work_window) AS a_end,
       lower(jb.work_window) AS b_start, upper(jb.work_window) AS b_end
FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b
WHERE op.horizon = 'long'
"""


def construction(start, end):
    before = 0.0
    for name, share in PHASES:  # construction phase inside the long window
        if name == "construction":
            return start + (end - start) * before, start + (end - start) * (before + share)
        before += share


def overlap_months(a, b):
    days = (min(a[1], b[1]) - max(a[0], b[0])).total_seconds() / 86400
    return max(days, 0) / MONTH_DAYS


def shifted(window, months):
    return window[0] + relativedelta(months=months), window[1] + relativedelta(months=months)


def min_delay(fixed, moving, need):
    """Whole months to delay `moving` so it overlaps `fixed` by `need` months, or None."""
    if (moving[1] - moving[0]).days / MONTH_DAYS < need or (fixed[1] - fixed[0]).days / MONTH_DAYS < need:
        return None
    for d in range(SEARCH_MONTHS + 1):
        if overlap_months(fixed, shifted(moving, d)) >= need - SLACK:
            return d
        if shifted(moving, d)[0] > fixed[1]:
            return None  # already past it, more delay only hurts
    return None


def mid(row):
    return round((float(row["savings_low"]) + float(row["savings_high"])) / 2)


def sentence(reason):
    r = reason["rule"]
    if r == "max_delay":
        return (f"Sharing would push {reason['project']} {reason['needed_months']} month{'s' if reason['needed_months'] != 1 else ''} "
                f"past its in-service date; your limit is {reason['limit_months']}.")
    if r == "drive_time":
        return f"The two sites are {reason['minutes']} minutes apart by road; your limit is {reason['limit']}."
    if r == "crew_taken":
        return (f"{reason['project']} already shares its crew on #{reason['by_opportunity']}, which saves more "
                f"(${reason['their_savings_mid']:,} vs ${reason['this_savings_mid']:,} at the midpoint).")
    if r == "no_overlap_possible":
        return (f"No delay makes construction overlap {reason['min_overlap_months']} months "
                f"(shortest construction phase is {reason['shortest_months']} months).")
    if r == "drive_unknown":
        return "Drive time is unknown, so it did not block this pair."
    return r


def accepted_sentence(d, limits):
    shift = d["shift"]
    drive = f"{d['drive_min']} minutes by road" if d["drive_min"] is not None else "drive time unknown"
    if shift:
        return (f"Share crews by delaying {shift['project']} {shift['months']} month{'s' if shift['months'] != 1 else ''} "
                f"(limit {limits['max_delay_months']}); construction then overlaps {d['overlap_months']} months, {drive}.")
    return f"Share crews: construction already overlaps {d['overlap_months']} months, {drive}."


def evaluate(row, limits):
    """Check one pair against the limits before crews are assigned."""
    con_a, con_b = construction(row["a_start"], row["a_end"]), construction(row["b_start"], row["b_end"])
    need = limits["min_overlap_months"]
    options = []
    da, db = min_delay(con_b, con_a, need), min_delay(con_a, con_b, need)
    if da is not None:
        options.append((da, "a"))
    if db is not None:
        options.append((db, "b"))
    reasons, shift, overlap = [], None, None
    drive = None if row["drive_min"] is None else round(float(row["drive_min"]))
    if not options:
        shortest = min((c[1] - c[0]).days / MONTH_DAYS for c in (con_a, con_b))
        reasons.append({"rule": "no_overlap_possible", "min_overlap_months": need, "shortest_months": round(shortest, 1)})
    else:
        months, side = min(options)  # smallest delay wins, project a on ties
        project = row[f"{side}_name"]
        if months > limits["max_delay_months"]:
            reasons.append({"rule": "max_delay", "project": project, "job_id": row[f"job_{side}"],
                            "needed_months": months, "limit_months": limits["max_delay_months"]})
        else:
            moved = shifted(con_a, months) if side == "a" else shifted(con_b, months)
            overlap = round(overlap_months(moved, con_b if side == "a" else con_a), 1)
            shift = {"job_id": row[f"job_{side}"], "project": project, "months": months} if months else None
    if drive is not None and drive > limits["max_drive_min"]:
        reasons.append({"rule": "drive_time", "minutes": drive, "limit": limits["max_drive_min"]})
    return reasons, shift, overlap, drive


def decide(rows, limits=None):
    limits = {**DEFAULTS, **(limits or {})}
    decisions, candidates = {}, []
    for row in rows:
        reasons, shift, overlap, drive = evaluate(row, limits)
        d = {"opportunity_id": row["id"], "a": row["a_name"], "b": row["b_name"], "job_a": row["job_a"], "job_b": row["job_b"],
             "savings_mid": mid(row), "drive_min": drive, "shift": shift, "overlap_months": overlap, "reasons": reasons}
        decisions[row["id"]] = d
        if not reasons:
            candidates.append(d)
    taken = {}  # job id -> decision that uses its crew
    for d in sorted(candidates, key=lambda d: (-d["savings_mid"], d["opportunity_id"])):  # biggest savings first
        clash = next((j for j in (d["job_a"], d["job_b"]) if j in taken), None)
        if clash:
            other = taken[clash]
            d["reasons"].append({"rule": "crew_taken", "project": d["a"] if clash == d["job_a"] else d["b"], "job_id": clash,
                                 "by_opportunity": other["opportunity_id"], "their_savings_mid": other["savings_mid"],
                                 "this_savings_mid": d["savings_mid"]})
            continue
        taken[d["job_a"]] = taken[d["job_b"]] = d
    out = []
    for d in decisions.values():
        d["decision"] = "share" if d["opportunity_id"] in {x["opportunity_id"] for x in taken.values()} else "no_share"
        notes = [] if d["drive_min"] is not None else [{"rule": "drive_unknown"}]
        d["sentence"] = accepted_sentence(d, limits) if d["decision"] == "share" else " ".join(sentence(r) for r in d["reasons"])
        d["notes"] = notes
        out.append(d)
    out.sort(key=lambda d: (d["decision"] != "share", -d["savings_mid"]))
    shared = [d for d in out if d["decision"] == "share"]
    summary = {"pairs": len(out), "shared": len(shared), "savings_mid_total": sum(d["savings_mid"] for d in shared),
               "rejected_by": {r: sum(1 for d in out if d["decision"] == "no_share" and any(x["rule"] == r for x in d["reasons"]))
                               for r in ("max_delay", "drive_time", "crew_taken", "no_overlap_possible")}}
    return limits, summary, out


def rows(conn):
    has_drive = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'opportunity' AND column_name = 'drive_min'").fetchone()
    return conn.execute(ROWS_SQL.format(drive="op.drive_min" if has_drive else "NULL::real")).fetchall()


def run(conn, limits=None):
    conn.execute(TABLE_SQL)
    clean = {k: int(round(float(v))) for k, v in (limits or {}).items() if k in DEFAULTS and v is not None}
    used, summary, decisions = decide(rows(conn), clean)
    row = conn.execute("INSERT INTO crew_plan (limits, summary, decisions) VALUES (%s, %s, %s) RETURNING id, run_at",
                       (json.dumps(used), json.dumps(summary), json.dumps(decisions))).fetchone()
    return {"plan_id": row["id"], "run_at": row["run_at"], "limits": used, "summary": summary, "decisions": decisions}


def latest(conn):
    conn.execute(TABLE_SQL)
    row = conn.execute("SELECT * FROM crew_plan ORDER BY id DESC LIMIT 1").fetchone()
    current = {r["id"] for r in conn.execute("SELECT id FROM opportunity WHERE horizon = 'long'").fetchall()}
    if not row or {d["opportunity_id"] for d in row["decisions"]} != current:  # data was rebuilt since the last run
        return run(conn, row["limits"] if row else None)
    return {"plan_id": row["id"], "run_at": row["run_at"], "limits": row["limits"], "summary": row["summary"], "decisions": row["decisions"]}


def explain(conn, opportunity_id=None, project=None):
    plan = latest(conn)
    q = (project or "").lower()
    hits = [d for d in plan["decisions"] if (opportunity_id is not None and d["opportunity_id"] == opportunity_id)
            or (q and (q in d["a"].lower() or q in d["b"].lower()))]
    return {"plan_id": plan["plan_id"], "limits": plan["limits"], "decisions": hits}
