from app.config import ACRE_M2, ASSUMPTIONS, MAX_DRIVE_MIN, TIERS

RANK = {name: i for i, (name, _) in enumerate(TIERS)}  # lower rank = closer tier, tiers stack
CHAIN_DAYS = 180  # back-to-back jobs this many days apart can still hand a crew over
SHARE = {"low": 0.5, "high": 1.0}  # how much of a mobilization one partner really avoids

PAIR_SQL = """SELECT a.voltage_kv AS a_kv, b.voltage_kv AS b_kv,
  lower(a.work_window) AS a_start, upper(a.work_window) AS a_end, lower(b.work_window) AS b_start, upper(b.work_window) AS b_end
FROM job a, job b WHERE a.id = %s AND b.id = %s"""


def merged(overrides=None):
    out = {k: {"low": v["low"], "high": v["high"]} for k, v in ASSUMPTIONS.items()}
    for key, val in (overrides or {}).items():
        if key in out:
            out[key].update({end: float(val[end]) for end in ("low", "high") if end in val})
    return out


def pair_from(r):
    gap = max((max(r["a_start"], r["b_start"]) - min(r["a_end"], r["b_end"])).days, 0)  # days between the two windows
    kvs = [k for k in (r["a_kv"], r["b_kv"]) if k]
    return {"kv": min(kvs) if kvs else None, "gap_days": gap}  # the smaller job is the one whose setup gets absorbed


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
    return {"same_time": round(same_time, 2), "drive": round(drive, 2), "size": size, "kv": kv, "gap_days": gap}


def savings(tier, overlap_m, overrides=None, drive_min=None, time_overlap=None, pair=None):
    a = merged(overrides)
    f = factors(time_overlap, drive_min, pair)
    t, d = f["same_time"], f["drive"]
    result = {"low": 0.0, "high": 0.0, "items": {}, "factors": f}
    for end in ("low", "high"):
        m = a["mobilization_usd"]
        mob = m[end] if f["size"] is None else m["low"] + f["size"] * (m["high"] - m["low"])  # known voltage picks one cost
        items = {}
        if t * d > 0:
            items["crew mobilization"] = mob * SHARE[end] * t * d
        if RANK[tier] <= RANK["site"] and t > 0 and d > 0:
            items["staging yard"] = a["yard_usd"][end] * SHARE[end] * t  # a shared yard only helps while both jobs run
        if RANK[tier] <= RANK["land"] and overlap_m > 0:
            acres = overlap_m * a["row_width_m"][end] / ACRE_M2
            items["shared right-of-way"] = acres * a["land_usd_per_acre"][end]  # easements and surveys keep, timing does not matter
        if tier == "crossing" and t > 0:
            items["coordinated outage"] = a["outage_usd"][end] * t
        result[end] = round(sum(items.values()), -3)
        for name, usd in items.items():
            result["items"].setdefault(name, {})[end] = round(usd, -3)
    return result


def savings_for(conn, op, overrides=None):
    return savings(op["tier"], op["overlap_m"], overrides, op["drive_min"], op["time_overlap"], pair_for(conn, op["job_a"], op["job_b"]))
