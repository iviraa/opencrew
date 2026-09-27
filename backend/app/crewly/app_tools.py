"""Crewly tools for the company app: overlaps from the logged-in company's side, and its collaboration requests."""
import os
import re
from datetime import date

import httpx

from app.companies import companies, name, partner
from app.crewly.act_tools import act_tools
from app.crewly.comms_tools import PROMPT as COMMS_PROMPT, comms_tools
from app.crewly.generate_tools import PROMPT as GENERATE_PROMPT, generate_tools
from app.stormlab.tools import PROMPT as STORMLAB_PROMPT, stormlab_tools
from app.crewly.incident_tools import INCIDENT_TOOLS
from app.crewly.memory_tools import memory_prompt, memory_tools
from app.crewly.more_tools import MORE_TOOLS
from app.crewly.outlook_tools import OUTLOOK_TOOLS
from app.crewly.tools import REGIONS, TOOLS, _opp_row
from app.crewly.workspace_tools import PROMPT as WORKSPACE_PROMPT, workspace_tools
from app.planner.tools import planner_tools
from app.scenario.tools import PROMPT as SCENARIO_PROMPT, scenario_tools
from app.queries import OPP_SQL



def find_company(q):
    """A company id from an id, login, name or short name."""
    q = (q or "").strip().lower()
    for c in companies().values():
        if q in (c["id"], (c["login"] or "").lower(), c["name"].lower(), c["short"].lower()):
            return c["id"]
    hits = [c["id"] for c in companies().values() if q and q in c["name"].lower()]
    return hits[0] if len(hits) == 1 else None


def _day(s):
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        raise ValueError(f"dates must look like 2027-03-01, got {s!r}")


def mine_sql(company):
    assert re.fullmatch(r"[a-z0-9_]+", company), company  # ids come from the org table, never from the user
    return OPP_SQL + f" WHERE op.horizon = 'long' AND '{company}' IN (ja.org_id, jb.org_id)"


def my_overlaps(ctx, conn, start_date=None, end_date=None, tier=None, region=None, partner_company=None, limit=10):
    s, e = _day(start_date), _day(end_date)
    who = find_company(partner_company) if partner_company else None
    if partner_company and not who:
        return {"error": f"no utility called {partner_company!r}", "utilities": sorted(c["name"] for c in companies().values())}, []
    sql = mine_sql(ctx["company"]) + " AND (%(t)s::text IS NULL OR op.tier = %(t)s) AND (%(p)s::text IS NULL OR %(p)s IN (ja.org_id, jb.org_id))"
    if s or e:  # both projects must be building at some point inside the range
        sql += """ AND ja.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)
                   AND jb.work_window && tstzrange(%(s)s::timestamptz, %(e)s::timestamptz)"""
    box = REGIONS.get((region or "").lower())
    if box:
        sql += " AND ST_Intersects(ST_Centroid(op.link::geometry), ST_MakeEnvelope(%(x0)s, %(y0)s, %(x1)s, %(y1)s, 4326))"
    rows = conn.execute(sql + " ORDER BY op.score DESC, op.distance_m LIMIT %(l)s",
                        {"t": tier, "p": who, "s": s, "e": e, "l": min(int(limit or 10), 25),
                         **dict(zip(("x0", "y0", "x1", "y1"), box or (0, 0, 0, 0)))}).fetchall()
    out = []
    for r in rows:
        row = _opp_row(r)
        row["partner"] = name(partner(r, ctx["company"]))
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
             "from": name(x["from_company"]), "to": name(x["to_company"]), "projects": x["summary"].get("title"),
             "status": x["status"], "our_or_their_note": x["note"], "reply_feedback": x["feedback"],
             "sent": x["created_at"][:16].replace("T", " "), "answered": (x["responded_at"] or "")[:16].replace("T", " ") or None} for x in r.json()]
    ids = list(dict.fromkeys(x["overlap_id"] for x in rows))
    return {"we_are": name(ctx["company"]), "count": len(rows), "requests": rows}, ([{"type": "show_overlaps", "ids": ids}] if ids else [])


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def hazard_exposure_tool(ctx):
    from app.hazards.exposure import PERIODS, assess

    def run(conn, site_or_zone, period="now7", month=None):
        kind = "zone" if str(site_or_zone).lstrip("#").isdigit() else "site"
        out = assess(conn, kind, str(site_or_zone).lstrip("#"), period if period in PERIODS else "now7", month)
        if not out:
            return {"error": f"no {kind} {site_or_zone}"}, []
        brief = {**out, "hazards": [{k: v for k, v in h.items() if k != "live"} | {"active": [x["label"] for x in h["live"][:3]]} for h in out["hazards"]]}
        return brief, [{"type": "hazards", "kind": kind, "id": out["id"], "period": out["period"], "month": month}]

    return (run, "Hazard exposure of one site (project id) or overlap zone (#id) in a period: which work-affecting hazards touch it "
                 "and the affected days (forecast for now7; low/high from ten years of history for weeks, season, month or the build "
                 "window). Assessment only. Opens the hazards view.", {
        "site_or_zone": {"type": "string", "description": "project id like gpc-123 or overlap #18"},
        "period": {"type": "string", "enum": list(PERIODS)}, "month": {"type": "integer", "description": "1-12, with period month"}}, ["site_or_zone"])


def hazard_cost_tool(ctx):
    from app.hazards import cost
    from app.hazards.exposure import PERIODS

    def run(conn, site_or_zone, period="month", month=None):
        kind = "zone" if str(site_or_zone).lstrip("#").isdigit() else "site"
        ident = str(site_or_zone).lstrip("#")
        period = period if period in PERIODS else "month"
        if kind == "site":
            c = cost.for_site(conn, ident, period, month)
            if not c:
                return {"error": f"no site {site_or_zone}"}, []
            brief = {k: v for k, v in c.items() if k not in ("phase_mix", "per_day")}
        else:
            got = cost.for_zone(conn, ident, period, month)
            if not got:
                return {"error": f"no overlap {site_or_zone}"}, []
            c, coord = got
            brief = {"period": period, "start": c["start"], "end": c["end"], "expected_extra_cost_usd": c["total"],
                     "sites": [{"name": s["name"], "expected_extra_cost_usd": s["total"], "hazards": [{"hazard": i["label"], "days": i["days"], "cost": i["total"]} for i in s["items"]]} for s in c["sites"]],
                     "coordinating": {"separate_usd": coord["separate"], "coordinated_usd": coord["coordinated"], "savings_usd": coord["savings"],
                                      "shared_standby_days": coord["items"][0]["shared_days"], "one_off_project_savings": coord["one_off"]},
                     "cheapest_months": [{"month": m["label"], "cost_per_30d_usd": m["cost_per_30d"], "saves_vs_period_usd": m["saves_vs_period"]} for m in coord["best_months"]],
                     "method": c["method"]}
        return brief, [{"type": "hazards", "kind": kind, "id": ident, "period": period, "month": month}]

    return (run, "Expected extra cost of weather in a period for one site (project id) or overlap (#id): affected days x standby or "
                 "demobilization cost plus storm-rate labor, with low/high ranges; for an overlap also what coordinating with the neighbor "
                 "saves (shared standby, one-off mobilization) and the three cheapest months to work the pair. Assessment only. Opens the hazards view.", {
        "site_or_zone": {"type": "string", "description": "project id like gpc-123 or overlap #18"},
        "period": {"type": "string", "enum": list(PERIODS)}, "month": {"type": "integer", "description": "1-12, with period month"}}, ["site_or_zone"])


def feasibility_tool(ctx):
    from app.feasibility.assess import assess

    def run(conn, opportunity_id, refresh=False):
        out = assess(conn, int(opportunity_id), ctx["company"], refresh=bool(refresh))
        if not out:
            return {"error": f"#{opportunity_id} is not one of our overlaps"}, []
        brief = {"overlap_id": out["opportunity_id"], "partner": name(out["partner"]) if out.get("partner") else None, "verdict": out["verdict"],
                 "score": out["score"], "narrative": out["narrative"],
                 "factors": [{"factor": f["label"], "verdict": f["verdict"], "evidence": f["evidence"][:2], "conditions": f["conditions"][:2]} for f in out["factors"]]}
        return brief, [{"type": "open_overlap", "id": out["opportunity_id"]}]

    return (run, "Feasibility assessment of one of our overlaps: can coordinating with the partner actually happen? Judges location, timing, "
                 "cost, forecast and season, news, the counterparty's history and future considerations, each with a verdict (strong, "
                 "possible, unlikely) and the evidence. Opens the overlap in the side panel.", {
        "opportunity_id": {"type": "integer"}, "refresh": {"type": "boolean", "description": "recompute instead of reusing today's assessment"}}, ["opportunity_id"])


def app_tools(ctx):
    tools = {
        "my_overlaps": (_bind(ctx, my_overlaps), "Overlaps between our projects and neighboring utilities' projects, best first. Optional date "
                        "range (both projects building inside it), tier, region and partner_company (a utility's name). Plots them on the map "
                        "and lists them in the chat as clickable cards.", {
            "start_date": {"type": "string", "description": "YYYY-MM-DD"}, "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "tier": {"type": "string", "enum": ["crossing", "land", "site", "crew"]},
            "region": {"type": "string", "description": "one of " + ", ".join(REGIONS)},
            "partner_company": {"type": "string", "description": "only overlaps with this utility, e.g. Duke Energy"},
            "limit": {"type": "integer", "description": "exactly how many to return; pass the number the user asked for"}}, []),
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
    for name in ("search_projects", "project_details"):  # the planner tools only knew two companies
        fn, desc, props, req = tools[name]
        tools[name] = (fn, desc, {**props, "org": {"type": "string", "description": "company id, e.g. " + ", ".join(list(companies())[:4])}}, req)
    tools.update(act_tools(ctx))
    tools.update(memory_tools(ctx))
    tools["hazard_exposure"] = hazard_exposure_tool(ctx)
    tools["hazard_cost"] = hazard_cost_tool(ctx)
    tools["assess_feasibility"] = feasibility_tool(ctx)
    tools.update(planner_tools(ctx))
    tools["news_for"] = news_tool(ctx)
    tools.update(generate_tools(ctx))
    tools.update(stormlab_tools(ctx))
    tools.update(scenario_tools(ctx))
    tools.update(comms_tools(ctx))
    tools.update(workspace_tools(ctx))
    return tools


def news_for(ctx, conn, company_or_overlap=None, days=90, impact=None):
    """Recent stories about us, a neighbor, or an overlap, with how each could affect the work."""
    from app.news import feed
    q = str(company_or_overlap or "").strip()
    m = re.fullmatch(r"#?(\d+)", q)
    if m:
        items, about = feed.for_overlap(conn, int(m.group(1)), days), f"overlap #{m.group(1)}"
    else:
        who = find_company(q) if q else ctx["company"]
        if not who:
            return {"error": f"no utility called {q!r}", "utilities": sorted(c["name"] for c in companies().values())}, []
        items, about = feed.for_org(conn, who, days, impact), name(who)
    rows = [{"title": i["title"], "source": i["source"], "date": (i["published"] or "")[:10], "impact": i["impact"], "affects_work": i["affects_work"],
             "summary": i["summary"], "linked_projects": len(i["job_ids"]), "linked_overlaps": i["opportunity_ids"][:5], "verified": i["verified"], "url": i["url"]}
            for i in items[:12]]
    return {"about": about, "days": days, "count": len(items), "stories": rows}, []


def news_tool(ctx):
    return (_bind(ctx, news_for), "Recent news about our company, a neighboring utility, or an overlap (#id): outages, damage, delays, "
            "opposition, regulatory decisions, supply chain, security. Each story says how it could affect the work and which projects it touches.", {
        "company_or_overlap": {"type": "string", "description": "a utility name, or an overlap id like #18; empty means our company"},
        "days": {"type": "integer"}, "impact": {"type": "string", "enum": ["delay", "damage", "outage", "opposition", "regulatory", "supply_chain", "security", "funding", "construction", "other"]}}, [])


def app_system(ctx):
    me = name(ctx["company"])
    return f"""You are Crewly, a friendly beaver in a hard hat who helps utility planners coordinate construction work.
You are talking with a planner at {me} ({ctx['company']}). Today is {date.today():%B %d, %Y}.
"Overlaps" are places where our planned transmission projects and a neighboring utility's projects are close in space and time, so
crews, land, yards and equipment could be shared. Each overlap has one partner utility (the "partner" field). Say "we/our" for {me}
and name the partner utility for them; never assume there is only one other company.

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
- For "how exposed is site/overlap X in <period>" call hazard_exposure. Report affected days as an assessment of the period
  (exposure, risk, likely affected days); never tell crews whether to work or send anyone anywhere.
- For "any news about X", "what is going on at <neighbor>", or "anything that could disrupt overlap #N" call news_for and report it as an
  assessment: what happened, how it could affect the work, and the source name. Never invent stories or details beyond the tool's summary.
- For "what does weather cost us in <period>" or "what do we save by coordinating with X in <period>" call hazard_cost and quote its
  low to high ranges as estimates; numbers only from the tool, never computed by you.
- For "is #X feasible / realistic / worth pursuing" or "why would coordinating on #X not work" call assess_feasibility and give the
  verdict, the one or two factors that decide it and what would make it work, all from the tool. It is an assessment of the pair,
  never an instruction to crews.
- For "plan our quarter/year", "what should we pursue" or "build a plan" call build_plan once (plan_status if one exists); it picks
  the pairs worth pursuing, the cheapest months to work each by weather history, savings and risks, and shows a plan card in the chat where the
  user accepts or skips items. Describe it with the tool's numbers only. For "why this pair/these months" call explain_plan_item.
- Keep replies short and warm: one to three sentences or a compact list. Refer to overlaps as "#id" with both project names.""" + GENERATE_PROMPT + STORMLAB_PROMPT + SCENARIO_PROMPT + COMMS_PROMPT + WORKSPACE_PROMPT + memory_prompt(ctx.get("memories"))
