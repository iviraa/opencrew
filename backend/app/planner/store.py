"""Saved plans, one active version per company and horizon; item states survive a rebuild."""
import json
from datetime import datetime, timezone

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS coordination_plan (
  id          SERIAL PRIMARY KEY,
  company_id  TEXT NOT NULL,
  horizon     TEXT NOT NULL,
  version     INT NOT NULL DEFAULT 1,
  items       JSONB NOT NULL DEFAULT '[]',
  totals      JSONB NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'active',
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
)
"""
CARRIED = ("state", "note", "request_id", "goal_id", "target_edited")  # what a person decided, kept across versions


def ensure(conn):
    conn.execute(TABLE_SQL)


def latest(conn, company, horizon):
    ensure(conn)
    return conn.execute("SELECT * FROM coordination_plan WHERE company_id = %s AND horizon = %s AND status = 'active' ORDER BY version DESC LIMIT 1",
                        (company, horizon)).fetchone()


def get(conn, plan_id, company):
    ensure(conn)
    return conn.execute("SELECT * FROM coordination_plan WHERE id = %s AND company_id = %s", (int(plan_id), company)).fetchone()


def carry(items, previous):
    """New items inherit the decisions made on the same overlap in the previous version."""
    before = {i["opportunity_id"]: i for i in (previous or [])}
    for it in items:
        old = before.get(it["opportunity_id"])
        if not old or old.get("state") == "proposed":
            continue
        for k in CARRIED:
            if old.get(k) is not None:
                it[k] = old[k]
        if old.get("target_edited"):
            it["target_start"], it["target_end"] = old["target_start"], old["target_end"]
    return items


def save(conn, company, horizon, items, totals):
    ensure(conn)
    prev = latest(conn, company, horizon)
    items = carry(items, prev["items"] if prev else None)
    version = (prev["version"] + 1) if prev else 1
    conn.execute("UPDATE coordination_plan SET status = 'archived', updated_at = now() WHERE company_id = %s AND horizon = %s AND status = 'active'",
                 (company, horizon))
    row = conn.execute("INSERT INTO coordination_plan (company_id, horizon, version, items, totals) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                       (company, horizon, version, json.dumps(items, default=str), json.dumps(totals, default=str))).fetchone()
    row["changed"] = changes(prev["items"] if prev else [], items)
    return row


def changes(before, after):
    b, a = {i["opportunity_id"] for i in before}, {i["opportunity_id"] for i in after}
    return {"added": sorted(a - b), "dropped": sorted(b - a)}


def update_item(conn, plan, item_id, patch):
    """Change one item's state, target months or note; returns the updated plan row."""
    items = plan["items"]
    hit = next((i for i in items if i["id"] == item_id), None)
    if not hit:
        return None
    if patch.get("state") in ("proposed", "accepted", "skipped"):
        hit["state"] = patch["state"]
    if patch.get("target_start") and patch.get("target_end"):
        hit["target_start"], hit["target_end"], hit["target_edited"] = patch["target_start"][:10], patch["target_end"][:10], True
    if "note" in patch:
        hit["note"] = (patch["note"] or "")[:1000]
    return conn.execute("UPDATE coordination_plan SET items = %s, updated_at = now() WHERE id = %s RETURNING *",
                        (json.dumps(items, default=str), plan["id"])).fetchone()


def set_goal(conn, plan, item_ids, goal_id):
    for it in plan["items"]:
        if it["id"] in item_ids:
            it["goal_id"] = goal_id
    return conn.execute("UPDATE coordination_plan SET items = %s, updated_at = now() WHERE id = %s RETURNING *",
                        (json.dumps(plan["items"], default=str), plan["id"])).fetchone()


def stamp():
    return datetime.now(timezone.utc).isoformat()
