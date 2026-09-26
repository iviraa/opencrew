import json
import os
import re
import sys

from app.crewly import agent
from app.crewly.tools import TOOLS
from app.db import connect


def opp(conn, a, b, horizon="long"):
    r = conn.execute("""SELECT op.id FROM opportunity op JOIN job ja ON ja.id = op.job_a JOIN job jb ON jb.id = op.job_b
                        WHERE op.horizon = %s AND ((ja.name ILIKE %s AND jb.name ILIKE %s) OR (ja.name ILIKE %s AND jb.name ILIKE %s))
                        ORDER BY op.score DESC LIMIT 1""", (horizon, a, b, b, a)).fetchone()
    return r and r["id"]


def jasper(conn):
    return opp(conn, "Jasper%Okatie%", "%MCINTOSH - PURRYSBURG%")


def hooks(conn):
    return opp(conn, "Hooks - Thurmond%", "EVANS PRIMARY - THURMOND DAM (USA) #5%")


def gpc_contact(conn):
    return conn.execute("SELECT id FROM contact WHERE org_id = 'gpc' ORDER BY id LIMIT 1").fetchone()["id"]


YARD = {"yard_usd": {"low": 500000, "high": 800000}}
CASES = [  # question, expected calls (args may be callables), facts that must appear (regex)
    ("Which DESC projects overlap Georgia Power work near Savannah?", [("find_overlaps", {"region": "savannah"})], ["Jasper", "MCINTOSH"]),
    ("Show me the crossing-tier opportunities.", [("find_overlaps", {"tier": "crossing"})], ["Hooks", "THURMOND"]),
    ("Explain the Jasper-Okatie line and McIntosh-Purrysburg reactors opportunity.",
     [("get_opportunity", lambda c: {"opportunity_id": jasper(c)})], [r"\b152\b", "site"]),
    ("If staging yards cost $500k to $800k, what would the Jasper-Okatie / McIntosh-Purrysburg pair save?",
     [("estimate_savings", lambda c: {"opportunity_id": jasper(c), "assumptions": YARD})], [r"\$550(,000|k)", r"\$950(,000|k)"]),
    ("What if staging yards cost $300k to $600k across the top opportunities?",
     [("set_assumptions", {"overrides": {"yard_usd": {"low": 300000, "high": 600000}}})], [r"\$350(,000|k)", r"\$750(,000|k)"]),
    ("Tell me about the Okatie-Bluffton rebuild.", [("project_details", {"query": "Okatie-Bluffton"})], ["2025", r"existing_path|existing (transmission )?line|mapped"]),
    ("Has the Thomson Primary second transformer been delayed?", [("project_details", {"query": "Thomson Primary second transformer"})], ["2031", "2033"]),
    ("Is KATHLEEN AREA IMPROVEMENTS on the map?", [("project_details", {"query": "Kathleen Area Improvements"})], [r"review|not on the map"]),
    ("How many projects still need a location?", [("review_queue", {})], [r"\b70\b"]),
    ("What equipment could the two utilities buy together or share?", [("equipment_matches", {})], ["Summerville", "THOMSON"]),
    ("How far apart are Jasper-Okatie and Goshen-McIntosh?", [("compare_projects", {"a": "Jasper Okatie", "b": "Goshen McIntosh"})], [r"7\.5"]),
    ("Draft a brief for the Hooks-Thurmond tie line pair.", [("draft_brief", lambda c: {"opportunity_id": hooks(c)})], ["Thurmond"]),
    ("Who can I contact about the Jasper-Okatie / McIntosh pair?", [("find_contacts", lambda c: {"opportunity_id": jasper(c)})], [r"transmission planning"]),
    ("Draft an intro email to Georgia Power about the Jasper-Okatie and McIntosh-Purrysburg pair.",
     [("draft_outreach", lambda c: {"opportunity_id": jasper(c), "contact_id": gpc_contact(c)})], [r"approv"]),
    ("Mark the Jasper-Okatie / McIntosh-Purrysburg opportunity as call scheduled.",
     [("set_status", lambda c: {"opportunity_id": jasper(c), "status": "call_scheduled"})], [r"call.scheduled"]),
    ("Switch to near-term and show only crew-tier pairs.", [("switch_view", {"horizon": "near", "tier": "crew"})], ["near"]),
    ("Show the equipment tab.", [("switch_view", {"tab": "equipment"})], ["equipment"]),
    ("Limit the timeline to 2025 through 2027 for DESC.", [("timeline_filter", {"years": [2025, 2027], "orgs": ["desc"]})], ["2025", "2027"]),
    ("Which near-term phases overlap?", [("find_overlaps", {"horizon": "near"})], [r"construction|clearing|survey|energization"]),
    ("Fly to Augusta.", [("focus_map", {"region": "augusta"})], ["augusta"]),
    ("What did Helene look like 6 hours after landfall?", [("storm_status", {"hours_from_landfall": 6})], [r"\b16\b"]),
    ("Where could both utilities stage crews 15 hours after Helene's landfall?", [("storm_status", {"hours_from_landfall": 15})], [r"\b41\b"]),
    ("Find the Mitchell - North Tifton reconductor.", [("search_projects", {"query": "Mitchell North Tifton"})], ["MITCHELL"]),
]
UI_TYPES = {"filter", "select", "storm", "reload", "fly", "status", "assumptions", "view", "timeline", "brief"}


def resolve(conn, args):
    return args(conn) if callable(args) else args


def same(a, b):
    return json.dumps(a, sort_keys=True).lower() == json.dumps(b, sort_keys=True).lower()


def offline(conn, calls):
    text, ui = "", []
    for name, args in calls:
        result, actions = TOOLS[name][0](conn, **resolve(conn, args))
        if "error" in result:
            return f"error: {result['error']}", ui
        text += json.dumps(result, default=str, ensure_ascii=False)
        ui += actions
    return text, ui


def online(conn, q, calls):
    res = agent.run(conn, [{"role": "user", "text": q}])
    called = res["tool_calls"]
    want = [(n, resolve(conn, a)) for n, a in calls]
    tools_ok = all(any(c["name"] == n for c in called) for n, _ in want)
    args_ok = all(any(c["name"] == n and all(same(c["args"].get(k), v) for k, v in a.items()) for c in called) for n, a in want)
    return res["reply"], res["ui_actions"], tools_ok, args_ok, not res["unsourced"]


def main():
    live = bool(os.environ.get("GEMINI_API_KEY"))
    rows, passed = [], 0
    with connect() as conn:
        for i, (q, calls, facts) in enumerate(CASES, 1):
            if live:
                text, ui, tools_ok, args_ok, guard_ok = online(conn, q, calls)
            else:
                text, ui = offline(conn, calls)
                tools_ok = args_ok = guard_ok = not text.startswith("error")
            facts_ok = all(re.search(f, text, re.I) for f in facts)
            ui_ok = all(a["type"] in UI_TYPES for a in ui)
            ok = tools_ok and args_ok and facts_ok and guard_ok and ui_ok
            passed += ok
            rows.append((i, q[:52], tools_ok, args_ok, facts_ok, guard_ok, ui_ok, ok))
            conn.rollback()  # status changes and drafts never stick
    mark = lambda b: "ok" if b else "FAIL"
    print(f"mode: {'live gemini' if live else 'offline (expected tool calls run directly)'}")
    print(f"{'#':>2} {'question':52} {'tools':5} {'args':5} {'facts':5} {'guard':5} {'ui':4} result")
    for i, q, t, a, f, g, u, ok in rows:
        print(f"{i:>2} {q:52} {mark(t):5} {mark(a):5} {mark(f):5} {mark(g):5} {mark(u):4} {'PASS' if ok else 'FAIL'}")
    print(f"\n{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
