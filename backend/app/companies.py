"""Every utility on crewly, read from the org table and cached for a few minutes."""
import hashlib
import time

from app.db import connect

TTL = 300
DISPLAY = {"desc": "Dominion Energy SC"}  # names the app already uses
FIXED = {"desc": "#2f6bff", "gpc": "#ff5d5d"}
PALETTE = ["#7c4dff", "#00b8a9", "#ff9f1c", "#e84393", "#2ec4b6", "#8e5cf7", "#f4a261", "#3a86ff", "#06d6a0", "#ef476f",
           "#118ab2", "#ffb703", "#9b5de5", "#00a6fb", "#f15bb5", "#43aa8b", "#fb8500", "#577590", "#c77dff", "#52b788"]
_cache = {"at": 0.0, "rows": {}}


def color(org_id, stored=None):
    if org_id in FIXED:
        return FIXED[org_id]
    return stored or PALETTE[int(hashlib.sha1(org_id.encode()).hexdigest(), 16) % len(PALETTE)]  # same color every load


def _row(r):
    name = DISPLAY.get(r["id"], r["name"])
    return {"id": r["id"], "name": name, "short": r.get("short") or name, "color": color(r["id"], r.get("color")),
            "state": r.get("state"), "planner": r.get("planner"), "login": r.get("login")}


def load(conn):
    rows = conn.execute("SELECT id, name, short, color, state, planner, login FROM org WHERE kind = 'utility' ORDER BY state NULLS LAST, name").fetchall()
    return {r["id"]: _row(r) for r in rows}


def companies(conn=None, fresh=False):
    if fresh or time.time() - _cache["at"] > TTL or not _cache["rows"]:
        if conn is not None:
            _cache["rows"] = load(conn)
        else:
            with connect() as c:
                _cache["rows"] = load(c)
        _cache["at"] = time.time()
    return _cache["rows"]


def name(org_id):
    c = companies().get(org_id)
    return c["name"] if c else org_id


def short(org_id):
    c = companies().get(org_id)
    return c["short"] if c else org_id


def partner(o, company):
    """The other side of an overlap, seen from `company`."""
    return o["b_org"] if o["a_org"] == company else o["a_org"]
