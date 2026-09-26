"""What two neighbouring projects stop paying for twice, priced from published unit costs.

Every line is quantity x unit price: the price comes from a key in config.ASSUMPTIONS (each one cites a document), the quantity from
config.DRIVERS. Lines carry the cost type they belong to, so the total can be shown as labour, equipment, travel, time, land and
overhead rather than one unexplained figure. docs/cost-savings-model.md shows the working and the sources.
"""
from app.config import ACRE_M2, ASSUMPTIONS, CATEGORIES, MAX_DRIVE_MIN, MILE_M, MOB_SPLIT, TIER_WEIGHT, TIERS, driver

RANK = {name: i for i, (name, _) in enumerate(TIERS)}  # lower rank = closer tier, tiers stack
CHAIN_DAYS = 180  # back-to-back jobs this many days apart can still hand a crew over
SHARE = {"low": 0.5, "high": 1.0}  # how much of a duplicated setup one partner really avoids
ENDS = ("low", "high")
DAYS_PER_MONTH = 30.44

PAIR_SQL = """SELECT a.voltage_kv AS a_kv, b.voltage_kv AS b_kv, a.cost_usd AS a_cost, b.cost_usd AS b_cost,
  lower(a.work_window) AS a_start, upper(a.work_window) AS a_end, lower(b.work_window) AS b_start, upper(b.work_window) AS b_end
FROM job a, job b WHERE a.id = %s AND b.id = %s"""


def merged(overrides=None):
    out = {k: {"low": v["low"], "high": v["high"]} for k, v in ASSUMPTIONS.items()}
    for key, val in (overrides or {}).items():
        if key in out:
            out[key].update({end: float(val[end]) for end in ("low", "high") if end in val})
    return out


def pair_from(r):
    a0, a1, b0, b1 = r["a_start"], r["a_end"], r["b_start"], r["b_end"]
    gap = max((max(a0, b0) - min(a1, b1)).days, 0)  # days between the two windows
    shared = max((min(a1, b1) - max(a0, b0)).days, 0)  # days both windows are open, what the recurring lines run on
    kvs = [k for k in (r["a_kv"], r["b_kv"]) if k]
    costs = [float(c) for c in (r.get("a_cost"), r.get("b_cost")) if c]
    return {"kv": min(kvs) if kvs else None, "gap_days": gap, "shared_days": shared,
            "cost_usd": min(costs) if costs else None}  # the smaller job is the one whose setup gets absorbed


def pair_for(conn, job_a, job_b):
    r = conn.execute(PAIR_SQL, (job_a, job_b)).fetchone()
    return pair_from(r) if r else {}


def factors(time_overlap=None, drive_min=None, pair=None):
    pair = pair or {}
    ov, gap = time_overlap or 0.0, pair.get("gap_days")
    chain = 0.5 * max(0.0, 1 - gap / CHAIN_DAYS) if gap is not None and ov == 0 else 0.0  # hand a crew from one job to the next
    same_time = 1.0 if time_overlap is None else max(ov, chain)
    drive = 1.0 if drive_min is None else (0.0 if drive_min > MAX_DRIVE_MIN else 1 - 0.3 * drive_min / MAX_DRIVE_MIN)  # longer commutes eat some of it: 100% next door, 70% at 45 min
    kv = pair.get("kv")
    size = None if kv is None else min(max((kv - 115) / (230 - 115), 0.0), 1.0)  # 115 kV sits at the low cost, 230 kV at the high
    return {"same_time": round(same_time, 2), "drive": round(drive, 2), "size": size, "kv": kv, "gap_days": gap,
            "shared_days": pair.get("shared_days"), "budget_usd": pair.get("cost_usd")}


def money(n):
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${n / 1e3:.0f}k" if n >= 1e3 else f"${n:,.0f}"


def span(lo, hi, fmt=money):
    return fmt(lo) if round(lo, 2) == round(hi, 2) else f"{fmt(lo)} to {fmt(hi)}"


def count(lo, hi):
    return span(lo, hi, lambda n: f"{n:,.0f}" if n >= 10 or n == int(n) else f"{n:.1f}" if n >= 1 else f"{n:.2f}")


def line_items(tier, overlap_m, a, f, pair):
    """Every duplicated cost one partner avoids: name, cost type, how many, the unit price behind it and a low/high range."""
    t, d = f["same_time"], f["drive"]
    shared_days = float(pair.get("shared_days") or 0)
    budget = pair.get("cost_usd")
    corridor_mi = overlap_m / MILE_M
    out = []

    def add(name, category, qty, basis, fn, over=None):
        vals = {end: round(max(fn(end), 0.0), -2) for end in ENDS}
        if vals["high"] > 0:
            out.append({"name": name, "category": category, "qty": qty, "basis": basis, "over": over, **vals})

    def mob(end):  # MISO publishes one figure per project; a known voltage places the pair inside it
        m = a["mobilization_usd"]
        return float(m[end]) if f["size"] is None else m["low"] + f["size"] * (m["high"] - m["low"])

    def worker_hour(end):  # one worker-hour, wages plus benefits
        return a["lineworker_hourly_usd"][end] * a["labor_burden_factor"][end]

    def crew_hour(end):
        return worker_hour(end) * driver("crew_size", end)

    mob_span = span(mob("low"), mob("high"))
    if t * d > 0:  # a second mobilization is only avoided when one crew and fleet can serve both sites
        add("Hauling the fleet in and out once", "travel", f"{count(*[driver('crew_moves', e) for e in ENDS])} crew moves",
            f"{MOB_SPLIT['travel']:.0%} of a {mob_span} project mobilization (MISO), the hauling share",
            lambda end: mob(end) * MOB_SPLIT["travel"] * SHARE[end] * t * d)
        add("Standing the site up and tearing it down once", "labor", f"{count(*[driver('setup_crew_days', e) for e in ENDS])} crew-days",
            f"{MOB_SPLIT['labor']:.0%} of a {mob_span} project mobilization (MISO), the crew share",
            lambda end: mob(end) * MOB_SPLIT["labor"] * SHARE[end] * t * d)
        add("One set of temporary facilities", "overhead", "1 site setup",
            f"{MOB_SPLIT['overhead']:.0%} of a {mob_span} project mobilization (MISO): site power, access and welfare",
            lambda end: mob(end) * MOB_SPLIT["overhead"] * SHARE[end] * t * d)
    if RANK[tier] <= RANK["site"] and t > 0 and d > 0:
        add("One laydown yard instead of two", "overhead", "1 yard",
            f"MISO site mobilization for an existing ({money(a['yard_usd']['low'])}) or new ({money(a['yard_usd']['high'])}) site",
            lambda end: a["yard_usd"][end] * SHARE[end] * t)
    if shared_days > 0 and d > 0:  # these two run with the calendar, so they need days when both sites are actually open
        add("Per diem and lodging for one crew, not two", "travel",
            f"{shared_days:,.0f} shared days x {count(*[driver('crew_size', e) for e in ENDS])} workers",
            f"GSA FY2027 standard CONUS per diem, {span(a['per_diem_usd_day']['low'], a['per_diem_usd_day']['high'], lambda n: f'${n:,.0f}')} a person-day",
            lambda end: shared_days * driver("crew_size", end) * a["per_diem_usd_day"][end] * driver("crew_share", end) * d,
            over=f"over {shared_days / DAYS_PER_MONTH:.0f} shared months")
    if RANK[tier] <= RANK["site"] and shared_days > 0 and d > 0:
        gear = ["crane_standby_usd_day", "digger_derrick_standby_usd_day", "puller_tensioner_standby_usd_day"]
        add("Crane and stringing gear held once", "equipment",
            f"{count(*[min(driver('gear_days', e), shared_days) for e in ENDS])} of {shared_days:,.0f} shared days",
            "FEMA 2025 equipment rates with Caltrans delay factors: crane, digger derrick and puller/tensioner standing idle",
            lambda end: min(driver("gear_days", end), shared_days) * sum(a[k][end] for k in gear) * driver("gear_share", end) * d)
    if RANK[tier] <= RANK["land"] and overlap_m > 0:  # the corridor is bought once whether or not the timing lines up
        # two lines in one corridor still need a corridor; what they avoid is the extra width, not a whole second right-of-way
        acres = {end: overlap_m * a["row_width_m"][end] * driver("row_shared_frac", end) / ACRE_M2 for end in ENDS}
        add("Width saved by sharing one corridor", "land", f"{count(acres['low'], acres['high'])} acres over {corridor_mi:.1f} mi",
            f"USDA NASS 2026 land value {span(a['land_usd_per_acre']['low'], a['land_usd_per_acre']['high'], lambda n: f'${n:,.0f}')} an acre on "
            f"{driver('row_shared_frac', 'low'):.0%}-{driver('row_shared_frac', 'high'):.0%} of a MISO right-of-way width "
            f"({a['row_width_m']['low']:.0f}-{a['row_width_m']['high']:.0f} m)",
            lambda end: acres[end] * a["land_usd_per_acre"][end])
        add("One route survey and environmental walk-down", "labor",
            f"{corridor_mi:.1f} mi x {count(*[driver('survey_days_per_mile', e) for e in ENDS])} crew-days a mile",
            f"BLS OEWS May 2025 line-worker wages loaded with BLS ECEC benefits, {span(crew_hour('low'), crew_hour('high'), lambda n: f'${n:,.0f}')} a crew-hour",
            lambda end: corridor_mi * driver("survey_days_per_mile", end) * crew_hour(end) * driver("shift_hours", end))
    if tier == "crossing" and t > 0:
        add("One switching crew for a shared outage", "labor",
            f"{driver('switch_crews'):.0f} crews x {driver('switch_shifts'):.0f} shifts x {driver('shift_hours'):.0f} h",
            f"Derived from line-worker crew-hours: {span(a['outage_usd']['low'], a['outage_usd']['high'])} an outage",
            lambda end: a["outage_usd"][end] * t)
    if budget and t > 0 and d > 0:  # coordinating stops the second project waiting, and waiting costs escalation
        months = {end: driver("months_pulled_in", end) * TIER_WEIGHT[tier] * t * d for end in ENDS}
        add("Months of waiting taken out of the schedule", "time",
            f"{count(months['low'], months['high'])} months on a {money(budget)} project",
            f"BLS construction escalation {a['escalation_pct_yr']['low']:g}-{a['escalation_pct_yr']['high']:g}% a year "
            "(ECI compensation to PPI construction goods)",
            lambda end: budget * a["escalation_pct_yr"][end] / 100 * months[end] / 12)
    return out


def by_category(lines):
    """Line totals grouped into the cost types the savings table shows, biggest first."""
    out = []
    for key, label, hint in CATEGORIES:
        rows = [ln for ln in lines if ln["category"] == key]
        if rows:
            out.append({"key": key, "label": label, "hint": hint, "lines": [ln["name"] for ln in rows],
                        **{end: sum(ln[end] for ln in rows) for end in ENDS}})
    return sorted(out, key=lambda c: -c["high"])


def savings(tier, overlap_m, overrides=None, drive_min=None, time_overlap=None, pair=None):
    a = merged(overrides)
    f = factors(time_overlap, drive_min, pair)
    lines = line_items(tier, overlap_m, a, f, pair or {})
    cats = by_category(lines)
    out = {end: sum(ln[end] for ln in lines) for end in ENDS}
    budget = pair.get("cost_usd") if pair else None
    return {**out, "items": {ln["name"]: {end: ln[end] for end in ENDS} for ln in lines},  # items: the flat name -> range view older callers read
            "lines": lines, "categories": cats, "factors": f,
            "share_of_budget": None if not budget else {end: round(out[end] / budget, 4) for end in ENDS}}  # against the smaller project, a sanity check


def savings_for(conn, op, overrides=None):
    return savings(op["tier"], op["overlap_m"], overrides, op["drive_min"], op["time_overlap"], pair_for(conn, op["job_a"], op["job_b"]))
