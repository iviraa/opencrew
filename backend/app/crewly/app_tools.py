"""Crewly tools for the company app: overlaps from the logged-in company's side, and its collaboration requests."""
import os
from datetime import date

import httpx

from app.crewly.act_tools import act_tools
from app.crewly.incident_tools import INCIDENT_TOOLS
from app.crewly.more_tools import MORE_TOOLS
from app.crewly.outlook_tools import OUTLOOK_TOOLS
from app.crewly.tools import REGIONS, TOOLS, _opp_row
from app.queries import OPP_SQL

NAMES = {"desc": "Dominion Energy SC", "gpc": "Georgia Power"}


def _day(s):
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        raise ValueError(f"dates must look like 2027-03-01, got {s!r}")


def mine_sql(company):
    return OPP_SQL + f" WHERE op.horizon = 'long' AND '{company}' IN (ja.org_id, jb.org_id)"  # company is checked against COMPANIES


def my_overlaps(ctx, conn, start_date=None, end_date=None, tier=None, region=None, limit=10):
    s, e = _day(start_date), _day(end_date)
    sql = mine_sql(ctx["company"]) + " AND (%(t)s::text IS NULL OR op.tier = %(t)s)"
    if s or e:  # both projects must be building at some point inside the range
        sql += """ AND ja.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)
                   AND jb.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)"""
    box = REGIONS.get((region or "").lower())
    if box:
        sql += " AND ST_Intersects(ST_Centroid(op.link::geometry), ST_MakeEnvelope(%(x0)s, %(y0)s, %(x1)s, %(y1)s, 4326))"
    rows = conn.execute(sql + " ORDER BY op.score DESC, op.distance_m LIMIT %(l)s",
                        {"t": tier, "s": s, "e": e, "l": min(int(limit or 10), 25),
                         **dict(zip(("x0", "y0", "x1", "y1"), box or (0, 0, 0, 0)))}).fetchall()
    out = []
    for r in rows:
        row = _opp_row(r)
        row["windows"] = {r["a_org"]: f"{r['a_start']:%b %Y} to {r['a_end']:%b %Y}", r["b_org"]: f"{r['b_start']:%b %Y} to {r['b_end']:%b %Y}"}
        out.append(row)
    result = {"count": len(rows), "date_range": [str(s) if s else None, str(e) if e else None], "region_known": bool(box) if region else None,
              "overlaps": out}
    if not rows and (s or e):
        result["when_overlaps_happen"] = busy_years(conn, ctx["company"])  # so the answer can point somewhere useful
    return result, ([{"type": "show_overlaps", "ids": [r["id"] for r in rows]}] if rows else [])


def busy_years(conn, company):
    """Years where both projects of an overlap are building, with how many overlaps each."""
    rows = conn.execute(f"""SELECT y, count(*) AS n FROM ({mine_sql(company)}) o,
                              generate_series(extract(year FROM greatest(o.a_start, o.b_start))::int,
                                              extract(year FROM least(o.a_end, o.b_end))::int) AS y
                            GROUP BY y ORDER BY y""").fetchall()
    return {str(r["y"]): r["n"] for r in rows}


def open_overlap(ctx, conn, opportunity_id):
    result, _ = TOOLS["get_opportunity"][0](conn, opportunity_id)
    if "error" in result:
        return result, []
    return result, [{"type": "open_overlap", "id": int(opportunity_id)}]


def collab_requests(ctx, conn, direction="any", status=None, limit=5):
    """Requests this company sent or received, newest first, read with the user's own login so row security applies."""
    q = {"select": "id,opportunity_id,from_company,to_company,summary,note,status,feedback,created_at,responded_at",
         "order": "created_at.desc", "limit": str(min(int(limit or 5), 20))}
    if direction == "sent":
        q["from_company"] = f"eq.{ctx['company']}"
    elif direction == "received":
        q["to_company"] = f"eq.{ctx['company']}"
    if status in ("pending", "approved", "declined"):
        q["status"] = f"eq.{status}"
    r = httpx.get(f"{os.environ['SUPABASE_URL'].rstrip('/')}/rest/v1/collab_request", params=q, timeout=10,
                  headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"], "Authorization": f"Bearer {ctx['token']}"})
    r.raise_for_status()
    rows = [{"request_id": x["id"], "overlap_id": x["opportunity_id"],
             "direction": "sent by us" if x["from_company"] == ctx["company"] else "sent to us",
             "from": NAMES[x["from_company"]], "to": NAMES[x["to_company"]], "projects": x["summary"].get("title"),
             "status": x["status"], "our_or_their_note": x["note"], "reply_feedback": x["feedback"],
             "sent": x["created_at"][:16].replace("T", " "), "answered": (x["responded_at"] or "")[:16].replace("T", " ") or None} for x in r.json()]
    ids = list(dict.fromkeys(x["overlap_id"] for x in rows))
    return {"we_are": NAMES[ctx["company"]], "count": len(rows), "requests": rows}, ([{"type": "show_overlaps", "ids": ids}] if ids else [])


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def app_tools(ctx):
    other = NAMES[ctx["other"]]
    tools = {
        "my_overlaps": (_bind(ctx, my_overlaps), f"Overlaps between our projects and {other}'s, best first. Optional date range (both projects "
                        "building inside it), tier and region. Plots them on the map and lists them in the chat as clickable cards.", {
            "start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "tier": {"type": "string", "enum": ["crossing", "land", "site", "crew"]},
            "region": {"type": "string", "description": "one of " + ", ".join(REGIONS)}, "limit": {"type": "integer"}}, []),
        "open_overlap": (_bind(ctx, open_overlap), "Full details for one overlap (both projects, windows, what can be shared, savings) "
                         "and open it in the side panel.", {"opportunity_id": {"type": "integer"}}, ["opportunity_id"]),
        "collab_requests": (_bind(ctx, collab_requests), "Our collaboration requests: ones we sent (and whether they were approved or "
                            "declined, with feedback) and ones sent to us. Newest first.", {
            "direction": {"type": "string", "enum": ["any", "sent", "received"]},
            "status": {"type": "string", "enum": ["pending", "approved", "declined"]}, "limit": {"type": "integer"}}, []),
    }
    shared = {**TOOLS, **MORE_TOOLS, **INCIDENT_TOOLS, **OUTLOOK_TOOLS}
    for name in ("estimate_savings", "search_projects", "project_details", "compare_projects", "focus_map",
                 "outlook", "site_hazards", "weather_alerts", "incidents_near"):
        tools[name] = shared[name]
    tools.update(act_tools(ctx))
    return tools


def app_system(ctx):
    me, other = NAMES[ctx["company"]], NAMES[ctx["other"]]
    return f"""You are Crewly, a friendly beaver in a hard hat who helps utility planners coordinate construction work.
You are talking with a planner at {me} ({ctx['company']}). The other company is {other} ({ctx['other']}). Today is {date.today():%B %d, %Y}.
"Overlaps" are places where our planned transmission projects and theirs are close in space and time, so crews, land, yards and
equipment could be shared. Say "we/our" for {me} and "{other}" for them.

Rules:
- Call a tool before stating any number. Every number you write must come from a tool result from this turn or the user's message.
  Never calculate or estimate numbers yourself.
- To show, list, find or filter overlaps (including by dates like "in March 2027" or "next year"), call my_overlaps once; the app plots
  them and shows clickable cards, so keep your text to a one or two sentence summary and do not repeat every row or id.
- Turn relative dates into start_date and end_date yourself from today's date (e.g. "next year", "this summer", "Q3 2025").
  Writing the dates you searched is fine. If nothing matches, say so and mention the years in when_overlaps_happen.
- When the user asks about one overlap, call open_overlap so the side panel opens.
- Questions about requests use collab_requests: "my last request" is direction sent, limit 1; "anything waiting for me" is
  direction received, status pending. Say which overlap it was about, its status, and quote their feedback if there is any.
- To send, approve or decline a request call propose_request or propose_answer. They only show a Confirm button; nothing
  happens until the user taps it, so say "Tap Confirm to send it" and never say it was sent, approved or declined.
  Write a short friendly note yourself if the user gave none, with no numbers of your own.
- For multi-step asks like "line up collaboration on our top 5 overlaps" call start_goal once; it drafts one request per
  overlap into a goal panel where the user reviews and sends them. For "how is my goal going" call goal_status.
- Weather and storm questions use outlook, weather_alerts or site_hazards; damage news uses incidents_near.
- Keep replies short and warm: one to three sentences or a compact list. Refer to overlaps as "#id" with both project names."""
