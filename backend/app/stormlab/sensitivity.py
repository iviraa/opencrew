"""Sensitivity: move one knob at a time and see which one moves the answer most (a tornado ranking)."""
from contextlib import contextmanager
from datetime import date

from app.config import ASSUMPTIONS, MAX_DRIVE_MIN
from app.engine.cost import savings_for
from app.hazards import cost as hcost
from app.stormlab import finding

METRICS = {"savings": "Coordination savings", "weather_cost": "Expected extra weather cost"}
SAVINGS_KEYS = ["mobilization_usd", "land_usd_per_acre", "row_width_m"]  # the savings model's own inputs, from config.ASSUMPTIONS
WEATHER_KEYS = ["crew_day_usd", "crane_standby_usd_day", "bucket_truck_standby_usd_day", "digger_derrick_standby_usd_day",
                "puller_tensioner_standby_usd_day", "demob_remob_usd", "storm_rate_multiplier"]
SWING = 0.25  # each knob is tried 25% below and above its base
OP_SQL = "SELECT id, job_a, job_b, tier, overlap_m, drive_min, time_overlap FROM opportunity WHERE id = %(id)s"


@contextmanager
def assumption(key, low, high):
    """Temporarily set one assumption's low and high; the models read config.ASSUMPTIONS at call time."""
    a = ASSUMPTIONS[key]
    keep = (a["low"], a["high"])
    a["low"], a["high"] = low, high
    try:
        yield
    finally:
        a["low"], a["high"] = keep


def short(label, n=36):
    """Chart-sized label: the part before the first colon or comma, trimmed."""
    head = label.split(":")[0].split(",")[0].strip()
    return head if len(head) <= n else head[: n - 1].rstrip() + "…"


def mid(x):
    return (float(x["low"]) + float(x["high"])) / 2


def savings_metric(conn, op, drive_min=None):
    o = {**op, "drive_min": op["drive_min"] if drive_min is None else drive_min}
    return mid(savings_for(conn, o))


def weather_metric(conn, op_id, month):
    cost, _ = hcost.for_zone(conn, op_id, "month", month)
    return mid(cost["total"])


def sensitivity(conn, company, opportunity_id, metric="savings", knobs=None, month=None):
    op = conn.execute(OP_SQL, {"id": int(opportunity_id)}).fetchone()
    if not op:
        raise ValueError(f"no overlap #{opportunity_id}")
    metric = metric if metric in METRICS else "savings"
    month = month or date.today().month
    keys = [k for k in (knobs or (SAVINGS_KEYS if metric == "savings" else WEATHER_KEYS)) if k in ASSUMPTIONS]
    extra = [k for k in (knobs or []) if k in ("drive_min", "shift_months")] or (["drive_min"] if metric == "savings" else ["shift_months"])

    def value(drive=None, m=None):
        return savings_metric(conn, op, drive) if metric == "savings" else weather_metric(conn, op["id"], m or month)

    base = value()
    rows = []
    for k in keys:
        a = ASSUMPTIONS[k]
        with assumption(k, float(a["low"]) * (1 - SWING), float(a["high"]) * (1 - SWING)):
            lo = value()
        with assumption(k, float(a["low"]) * (1 + SWING), float(a["high"]) * (1 + SWING)):
            hi = value()
        rows.append({"knob": k, "label": short(a.get("label", k)), "low_setting": round(lo), "high_setting": round(hi), "swing": round(abs(hi - lo)),
                     "setting": f"{SWING:.0%} below and above"})
    for k in extra:
        if k == "drive_min" and op["drive_min"] is not None:
            lo, hi = value(drive=max(op["drive_min"] * (1 - SWING), 0)), value(drive=min(op["drive_min"] * (1 + SWING), MAX_DRIVE_MIN * 2))
            rows.append({"knob": k, "label": "Drive time between the sites", "low_setting": round(lo), "high_setting": round(hi), "swing": round(abs(hi - lo)),
                         "setting": f"{op['drive_min'] * (1 - SWING):.0f} to {op['drive_min'] * (1 + SWING):.0f} min"})
        if k == "shift_months":
            lo, hi = value(m=(month - 4) % 12 + 1), value(m=month % 12 + 1)
            rows.append({"knob": k, "label": "Work three months earlier or later", "low_setting": round(lo), "high_setting": round(hi), "swing": round(abs(hi - lo)),
                         "setting": "-3 and +3 months"})
    rows.sort(key=lambda r: -r["swing"])
    unit = "usd"
    b = finding.metric(metric, round(base), unit=unit, label=f"{METRICS[metric]} (base)")
    top = rows[0] if rows else None
    scen = {metric: finding.metric(metric, round(top["high_setting"]) if top else round(base), unit=unit, label=f"{METRICS[metric]} with {top['label'].lower()} +{SWING:.0%}" if top else METRICS[metric])}
    chart = {"title": f"What moves {METRICS[metric].lower()} on overlap #{op['id']}", "kind": "bar", "x": [r["label"] for r in rows], "unit": "usd",
             "series": [{"name": f"swing ({SWING:.0%} below to above)", "values": [r["swing"] for r in rows], "color": "#5b2bb5"}],
             "source": "engine.cost and hazards.cost with each assumption moved on its own", "orientation": "horizontal"}
    evidence = [f"base {METRICS[metric].lower()}: {finding.usd(base)}"] + [f"{r['label']}: {finding.usd(r['low_setting'])} to {finding.usd(r['high_setting'])} (swing {finding.usd(r['swing'])})" for r in rows[:4]]
    f = finding.make("sensitivity", f"Sensitivity of {METRICS[metric].lower()}, overlap #{op['id']}", f"Which assumption moves the {METRICS[metric].lower()} on #{op['id']} most?",
                     {"opportunity_id": op["id"], "metric": metric, "knobs": keys + extra, "month": month}, {metric: b}, scen,
                     notes=[f"Each knob is moved {SWING:.0%} below and above its base while the others stay put; the swing is the difference. "
                            "Assumption sources are the ones shown on the cost cards. Estimates for assessment, never work orders."],
                     evidence=evidence, knobs=[finding.knob("metric", "select", metric, "Metric", options=list(METRICS)),
                                                finding.knob("month", "months", month, "Month (weather cost)")],
                     sources=sorted({ASSUMPTIONS[k].get("source", "") for k in keys if ASSUMPTIONS[k].get("source")}),
                     chart=chart, rows=rows)
    return finding.save(conn, company, f)
