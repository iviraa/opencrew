"""Scheduled rebuilds: when a company's plan changes, a suggestion lands in its bell."""
from app.planner import build, store


def refresh(company, horizon="quarter"):
    from app.crewly.proactive import _rest
    from app.db import connect
    with connect() as conn:
        plan = build.build(conn, company, horizon)
        row = store.save(conn, company, plan["horizon"], plan["items"], plan["totals"])
    added, dropped = row["changed"]["added"], row["changed"]["dropped"]
    if row["version"] > 1 and not added and not dropped:
        return {"company": company, "version": row["version"], "changed": False}
    parts = [f"{len(added)} new feasible pair{'s' if len(added) != 1 else ''}" if added else "", f"{len(dropped)} dropped" if dropped else ""]
    title = ("Plan updated: " + ", ".join(p for p in parts if p)) if row["version"] > 1 else f"Your {horizon} plan is ready: {len(row['items'])} pairs"
    t = row["totals"]
    body = f"Expected savings ${round(t['savings']['low'] / 1e3)}k to ${round(t['savings']['high'] / 1e3)}k; {t['actions'].get('send request', 0)} ready to ask."
    try:
        _rest("notification", "POST", json={"company_id": company, "kind": "suggestion", "dedup_key": f"plan:{company}:{row['version']}",
                                           "title": title[:80], "body": body, "action": {"type": "plan", "horizon": horizon}},
              headers={"Prefer": "return=representation"})
    except Exception as e:  # a bell we cannot reach is not a failed plan
        print("plan suggestion not posted:", company, e)
    return {"company": company, "version": row["version"], "changed": True, "added": added, "dropped": dropped}
