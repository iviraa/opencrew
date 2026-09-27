"""Editing a saved plan: move a pair's months, skip or accept it, undo; each edit re-prices the pair, recomputes the totals and is logged with its effect."""
import json
from datetime import date, datetime, timezone

from dateutil.relativedelta import relativedelta

from app.planner import build

ENDS = build.ENDS
KEEP = ("state", "target_start", "target_end", "target_edited", "weather", "risks")  # what an undo puts back


def _d(v):
    if isinstance(v, date):
        return v
    t = str(v).strip()[:10]
    try:
        return date.fromisoformat(t if len(t) > 7 else t + "-01")  # "2025-04" means April 2025
    except ValueError:
        raise ValueError(f"months are written YYYY-MM, like 2025-04; got {v!r}") from None


def _usd(n):
    n = float(n or 0)
    sign = "-" if n < 0 else "+"
    n = abs(n)
    return sign + (f"${n / 1e6:.1f}M" if n >= 1e6 else f"${round(n / 1e3)}k" if n >= 1e3 else f"${round(n)}")


def _mon(v):
    return f"{_d(v):%b %Y}"


def totals(plan):
    t = plan["totals"]
    return build.totals_for(plan["items"], t.get("considered", 0), t.get("skipped", {}), tuple(t["period"]) if t.get("period") else None, t.get("note", ""))


def reprice(conn, item, start, end):
    """Weather cost and affected days for the pair in its new months, from the same ten-year history the planner chose months with."""
    op = conn.execute("SELECT id, job_a, job_b, drive_min FROM opportunity WHERE id = %s", (item["opportunity_id"],)).fetchone()
    if not op:
        raise ValueError(f"overlap #{item['opportunity_id']} no longer exists")
    months = build.Pricer(conn).pair(op)
    run = build.months_between(start, end)
    cost = {e: round(sum(months[m.month]["cost"][e] for m in run), -2) for e in ENDS}
    days = {e: round(sum(months[m.month]["days"][e] for m in run), 1) for e in ENDS}
    naive = item["weather"]["naive"]
    w = {**item["weather"], "target": cost, "days": days, "avoided": {e: max(naive[e] - cost[e], 0) for e in ENDS}}
    common = (_d(item["window"]["common"][0]), _d(item["window"]["common"][1]))
    risks = [r for r in item["risks"] if not r.startswith("up to ") and not r.startswith("target months")]
    if days["high"] >= 3:
        risks.append(f"up to {days['high']} weather-affected days in the target months")
    if start < common[0] or end > common[1]:
        risks.append(f"target months run outside the shared build window ({_mon(common[0])} to {_mon(common[1])})")
    return w, risks


def _window(item, change):
    """The new months from start/end or a shift in months; always whole months."""
    if change.get("shift_months") not in (None, "", 0):
        k = int(change["shift_months"])
        s, e = _d(item["target_start"]) + relativedelta(months=k), _d(item["target_end"]) + relativedelta(months=k)
    elif change.get("start") and change.get("end"):
        s, e = _d(change["start"]), _d(change["end"])
    else:
        raise ValueError("a move needs start and end months (YYYY-MM) or shift_months")
    s, e = build.first(s), build.last(e)
    if e < s:
        raise ValueError("the end month is before the start month")
    if (e.year - s.year) * 12 + e.month - s.month > 23:
        raise ValueError("a coordinated push is at most two years long")
    common = (_d(item["window"]["common"][0]), _d(item["window"]["common"][1]))
    if e < common[0] or s > common[1]:
        raise ValueError(f"#{item['id']} can only be coordinated while both projects build: {_mon(common[0])} to {_mon(common[1])}")
    return s, e


def apply(conn, plan, changes):
    """Apply changes in order and save; returns (plan row, list of what each change did). Nothing is saved if any change is invalid."""
    items = plan["items"]
    t = dict(plan["totals"])
    t.setdefault("built", {k: t.get(k) for k in ("savings", "weather_avoided")} | {"weather_cost": _weather_cost(items)})  # the plan as built, for "before your edits"
    log = list(t.get("edits") or [])
    done = []
    for ch in changes:
        action = (ch.get("action") or "").lower()
        if action == "undo":
            if not log:
                raise ValueError("there is no edit to undo")
            last = log.pop()
            for iid, before in last["restore"].items():
                it = next((i for i in items if i["id"] == iid), None)
                if it:
                    it.update(before)
            done.append({"summary": f"Undid: {last['summary']}"})
            continue
        targets = _targets(items, ch, plan["company_id"])
        restore = {it["id"]: {k: json.loads(json.dumps(it.get(k), default=str)) for k in KEEP} for it in targets}
        wc_before, sv_before = _weather_cost(items), _savings(items)
        parts = []
        for it in targets:
            if action == "move":
                s, e = _window(it, ch)
                old = (it["target_start"], it["target_end"])
                old_cost = it["weather"]["target"]
                it["weather"], it["risks"] = reprice(conn, it, s, e)
                it["target_start"], it["target_end"], it["target_edited"] = str(s), str(e), True
                diff = {x: it["weather"]["target"][x] - old_cost[x] for x in ENDS}
                parts.append(f"moved #{it['id']} from {_mon(old[0])}–{_mon(old[1])} to {_mon(s)}–{_mon(e)}; weather cost {_usd(diff['low'])} to {_usd(diff['high'])}")
            elif action in ("skip", "accept", "propose"):
                it["state"] = {"skip": "skipped", "accept": "accepted", "propose": "proposed"}[action]
                parts.append(f"{ {'skip': 'skipped', 'accept': 'accepted', 'propose': 'reopened'}[action]} #{it['id']}")
            else:
                raise ValueError("action must be move, skip, accept, propose or undo")
        wc_after, sv_after = _weather_cost(items), _savings(items)
        effect = {"savings": {x: round(sv_after[x] - sv_before[x]) for x in ENDS}, "weather_cost": {x: round(wc_after[x] - wc_before[x]) for x in ENDS}}
        summary = "; ".join(parts) if len(parts) <= 3 else f"{parts[0].split(' #')[0]} {len(parts)} pairs ({', '.join('#' + i['id'] for i in targets)})"
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action, "items": [i["id"] for i in targets],
                 "summary": summary[0].upper() + summary[1:], "effect": effect, "restore": restore}
        log.append(entry)
        done.append({k: entry[k] for k in ("summary", "effect", "items")})
    for i in items:  # conflicts are recomputed from the new months
        i["conflicts"] = []
    build.mark_conflicts(items)
    new = totals({**plan, "items": items})
    new["built"], new["edits"], new["weather_cost"] = t["built"], log[-30:], _weather_cost(items)
    row = conn.execute("UPDATE coordination_plan SET items = %s, totals = %s, updated_at = now() WHERE id = %s RETURNING *",
                       (json.dumps(items, default=str), json.dumps(new, default=str), plan["id"])).fetchone()
    return row, done


def _live(items):
    return [i for i in items if i["state"] != "skipped"]


def _weather_cost(items):
    return {e: round(sum(i["weather"]["target"][e] for i in _live(items))) for e in ENDS}


def _savings(items):
    return {e: round(sum(i["savings"][e] for i in _live(items))) for e in ENDS}


def _targets(items, ch, company):
    """The items a change is about: an item id (the overlap id), a list of ids, or every pair with a partner."""
    ids = [str(x).lstrip("#") for x in (ch.get("item_ids") or ([ch["item_id"]] if ch.get("item_id") else []))]
    if ch.get("partner"):
        from app.crewly.app_tools import find_company
        who = find_company(ch["partner"])
        if not who:
            raise ValueError(f"no utility called {ch['partner']!r}")
        hits = [i for i in items if i["partner"] == who]
        if not hits:
            raise ValueError(f"the plan has no pairs with {ch['partner']}")
        return hits
    if not ids:
        raise ValueError("say which pair: item_id (the overlap id), item_ids, or partner")
    hits = [i for i in items if i["id"] in ids]
    missing = [x for x in ids if x not in {i["id"] for i in hits}]
    if missing:
        raise ValueError(f"not in this plan: {', '.join('#' + m for m in missing)}; the plan has {', '.join('#' + i['id'] for i in items)}")
    return hits


def describe(plan):
    """Before your edits against now, for the tool result, the card and the report."""
    t = plan["totals"]
    b = t.get("built")
    if not b:
        return None  # never edited
    now_wc = t.get("weather_cost") or _weather_cost(plan["items"])
    return {"edits": len(t["edits"]), "savings": {"built": b["savings"], "now": t["savings"]}, "weather_cost": {"built": b["weather_cost"], "now": now_wc},
            "weather_avoided": {"built": b["weather_avoided"], "now": t["weather_avoided"]},
            "log": [{"at": e["at"], "summary": e["summary"], "effect": e["effect"]} for e in t["edits"]]}
