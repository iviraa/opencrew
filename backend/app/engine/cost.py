from app.config import ACRE_M2, ASSUMPTIONS, MAX_DRIVE_MIN, TIERS

RANK = {name: i for i, (name, _) in enumerate(TIERS)}  # lower rank = closer tier, tiers stack


def merged(overrides=None):
    out = {k: {"low": v["low"], "high": v["high"]} for k, v in ASSUMPTIONS.items()}
    for key, val in (overrides or {}).items():
        if key in out:
            out[key].update({end: float(val[end]) for end in ("low", "high") if end in val})
    return out


def savings(tier, overlap_m, overrides=None, drive_min=None):
    a = merged(overrides)
    road_ok = drive_min is None or drive_min <= MAX_DRIVE_MIN  # crews and yards only help within a 45 min drive
    result = {"low": 0.0, "high": 0.0, "items": {}}
    for end in ("low", "high"):
        items = {"crew mobilization": a["mobilization_usd"][end]} if road_ok else {}
        if RANK[tier] <= RANK["site"] and road_ok:
            items["staging yard"] = a["yard_usd"][end]
        if RANK[tier] <= RANK["land"] and overlap_m > 0:
            acres = overlap_m * a["row_width_m"][end] / ACRE_M2
            items["shared right-of-way"] = acres * a["land_usd_per_acre"][end]
        if tier == "crossing":
            items["coordinated outage"] = a["outage_usd"][end]
        result[end] = round(sum(items.values()), -3)
        for name, usd in items.items():
            result["items"].setdefault(name, {})[end] = round(usd, -3)
    return result
