"""Printable reports Crewly can hand over: feasibility, cost analysis, hazard exposure, the plan, or a pack for one overlap."""
import html
import json
from datetime import date

from app.companies import name, short
from app.config import MILE_M

KINDS = {
    "feasibility": ("Feasibility assessment", ["verdict", "factors", "conditions", "shifts"]),
    "cost_analysis": ("Cost analysis", ["savings", "weather", "coordination"]),
    "hazard_exposure": ("Hazard exposure", ["now7", "season", "month"]),
    "plan": ("Coordination plan", ["totals", "items", "risks"]),
    "pack": ("Overlap pack", ["brief", "feasibility", "cost_analysis", "hazard_exposure"]),
    "finding": ("Experiment finding", ["stack", "metrics", "deltas", "notes", "evidence", "sources"]),
    "agenda": ("Coordination call agenda", ["context", "decisions", "data", "questions", "logistics"]),
    "memo": ("Cost-sharing memo", ["purpose", "projects", "savings", "timing", "split", "risks", "next_steps"]),
}

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS report (
  id         SERIAL PRIMARY KEY,
  company_id TEXT NOT NULL,
  kind       TEXT NOT NULL,
  ref_id     TEXT,
  title      TEXT NOT NULL,
  sections   TEXT[] NOT NULL DEFAULT '{}',
  html       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CSS = """
body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1b2447;max-width:860px;margin:32px auto;padding:0 24px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:2px solid #dfe6f2;padding-bottom:4px}h3{font-size:14px;margin:14px 0 4px}
.sub{color:#5e6a8a;margin-bottom:18px}table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}th,td{border:1px solid #dfe6f2;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f5f8fd}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;background:#efe8fb;color:#4a1f9e}.strong{background:#dff6ec;color:#12a36b}.possible{background:#fff3d9;color:#8a5a00}.unlikely{background:#ffe8e8;color:#c23b3b}
.note{color:#5e6a8a;font-size:12px}ul{padding-left:18px}.print{position:fixed;top:12px;right:12px;padding:8px 14px;border:0;border-radius:999px;background:#5b2bb5;color:#fff;font-weight:600;cursor:pointer}
@media print{.print{display:none}body{margin:0}h2{page-break-after:avoid}}
"""

esc = html.escape


def usd(n):
    n = float(n or 0)
    sign, a = ("-" if n < 0 else ""), abs(n)
    return sign + (f"${a / 1e6:.1f}M" if a >= 1e6 else f"${round(a / 1e3)}k" if a >= 1e3 else f"${round(a)}")


def rng(r):
    return f"{usd(r['low'])} to {usd(r['high'])}" if isinstance(r, dict) else usd(r)


def chip(v):
    return f'<span class="chip {esc(v)}">{esc(str(v).title())}</span>'


def table(cols, rows):
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def page(title, sub, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title><style>{CSS}</style></head><body>"
            f"<button class='print' onclick='window.print()'>Print / Save as PDF</button><h1>{esc(title)}</h1><div class='sub'>{esc(sub)}</div>{body}"
            "<p class='note'>Estimates for assessment, never work orders. Distances, days and dollar ranges come from deterministic models over public data.</p></body></html>")


# ---------- sections ----------

def sec_feasibility(conn, company, opp, sections):
    from app.feasibility.assess import assess
    a = assess(conn, opp, company)
    if not a:
        raise ValueError(f"#{opp} is not one of our overlaps")
    out = [f"<h2>Feasibility</h2><p>{chip(a['verdict'])} score {a['score']:.2f}</p><p>{esc(a['narrative'])}</p>"]
    if "factors" in sections:
        out.append(table(["Factor", "Verdict", "Evidence"], [[f["label"], f["verdict"], "; ".join(f["evidence"][:3])] for f in a["factors"]]))
    if "conditions" in sections:
        conds = [(f["label"], c) for f in a["factors"] for c in f.get("conditions", [])[:2]]
        if conds:
            out.append("<h3>What would make it work</h3><ul>" + "".join(f"<li><b>{esc(l)}:</b> {esc(c)}</li>" for l, c in conds) + "</ul>")
    if "shifts" in sections:
        opts = next((f.get("options") for f in a["factors"] if f.get("options")), None)
        if opts:
            out.append("<h3>Shift options</h3>" + table(["Shift (months)", "Shared window", "Change", "Weather cost delta"],
                       [[o["months"], f"{round(o['overlap'] * 100)}%", f"{round(o['overlap_delta'] * 100):+}%", rng(o["weather_cost_delta"]) if o.get("weather_cost_delta") else "n/a"] for o in opts]))
    return "".join(out)


def sec_cost(conn, company, opp, sections):
    from app.engine.cost import savings_for
    from app.hazards import cost
    from app.queries import OPP_SQL
    op = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp,)).fetchone()
    if not op or company not in (op["a_org"], op["b_org"]):
        raise ValueError(f"#{opp} is not one of our overlaps")
    out = ["<h2>Cost analysis</h2>"]
    if "savings" in sections:
        s = savings_for(conn, op)
        out.append(f"<p>Coordinating saves <b>{rng(s)}</b>.</p>" + table(["Cost type", "Low", "High"], [[k, usd(v["low"]), usd(v["high"])] for k, v in s["items"].items()]))
    got = cost.for_zone(conn, opp, "month") if {"weather", "coordination"} & set(sections) else None
    if got:
        c, coord = got
        if "weather" in sections:
            out.append(f"<h3>Weather in a typical {esc(str(c['start'])[:7])}</h3><p>Expected extra cost <b>{rng(c['total'])}</b>.</p>"
                       + table(["Site", "Hazard", "Affected days", "Cost"], [[site["name"], i["label"], f"{i['days']['low']} to {i['days']['high']}", rng(i["total"])] for site in c["sites"] for i in site["items"]]))
        if "coordination" in sections:
            out.append(f"<h3>Coordinating with the neighbor</h3><p>Separately {rng(coord['separate'])}, together {rng(coord['coordinated'])}, saving <b>{rng(coord['savings'])}</b>.</p>"
                       + table(["Cheapest months", "Cost per 30 days", "Saves vs this period"], [[m["label"], rng(m["cost_per_30d"]), rng(m["saves_vs_period"])] for m in coord["best_months"]]))
        out.append(f"<p class='note'>{esc(c['method'])}</p>")
    return "".join(out)


def sec_hazards(conn, company, ident, sections):
    from app.hazards.exposure import assess
    kind = "zone" if str(ident).isdigit() else "site"
    out = ["<h2>Hazard exposure</h2>"]
    labels = {"now7": "Next 7 days", "season": "Next season", "month": "Typical month"}
    for p in ("now7", "season", "month"):
        if p not in sections:
            continue
        e = assess(conn, kind, ident, p)
        if not e:
            raise ValueError(f"no {kind} {ident}")
        rows = [[h["label"], h["affected_days"].get("forecast", ""), f"{h['affected_days'].get('low', '')} to {h['affected_days'].get('high', '')}", ", ".join(x["label"] for x in h.get("live", [])[:2])] for h in e["hazards"]]
        out.append(f"<h3>{labels[p]} ({esc(str(e['start']))} to {esc(str(e['end']))})</h3>" + table(["Hazard", "Forecast days", "History low to high", "Active"], rows))
    return "".join(out)


def sec_plan(conn, company, horizon, sections):
    row = plan_context(conn, company, horizon)
    t, items = row["totals"], row["items"]
    out = [f"<h2>Coordination plan, {esc(row['horizon'])} (v{row['version']})</h2>"]
    if "totals" in sections:
        out.append(f"<p>Expected savings <b>{rng(t['savings'])}</b>, weather cost avoided {rng(t['weather_avoided'])}. "
                   f"{esc(json.dumps(t.get('verdicts')))}{(' ' + esc(t['note'])) if t.get('note') else ''}</p>")
    if "items" in sections:
        out.append(table(["Overlap", "Ours", "Partner", "Verdict", "Months", "Savings", "Action", "State"],
                         [[f"#{i['id']}", i["ours"], i["partner_name"], i["verdict"], f"{i['target_start'][:7]} to {i['target_end'][:7]}", rng(i["savings"]), i["action"], i["state"]] for i in items]))
    if "risks" in sections:
        risks = [(f"#{i['id']}", r) for i in items for r in i.get("risks", [])[:2]]
        if risks:
            out.append("<h3>Risks</h3><ul>" + "".join(f"<li><b>{esc(a)}:</b> {esc(str(r))}</li>" for a, r in risks) + "</ul>")
    return "".join(out)


def sec_finding(conn, company, ref, sections):
    """One experiment: the question, what was changed, base against scenario, and what moved."""
    from app.scenario import experiments
    f = experiments.get(conn, int(ref), company) if str(ref).isdigit() else None
    if not f:
        raise ValueError("this report needs a finding id")
    fmt = lambda v, u: (f"${v:,.0f}" if u == "USD" else f"{v:g}{'%' if u == '%' else ''}" + (f" {u}" if u and u not in ("USD", "%") else "")) if isinstance(v, (int, float)) else str(v if v is not None else "")  # noqa: E731
    out = [f"<h2>{esc(f['title'])}</h2><p class='sub'>{esc(f.get('question') or '')}</p>"]
    changes = f["params"].get("changes") if f["kind"] == "compose" else [{"kind": f["kind"], "params": {k: v for k, v in f["params"].items() if k != "changes"}}]
    if "stack" in sections and changes:
        out.append("<h3>What was changed</h3>" + table(["Change", "Settings"], [[c["kind"].replace("_", " "), esc(json.dumps({k: v for k, v in c["params"].items() if k != "base_finding_id"}, default=str)[:200])] for c in changes]))
    base, scen = f["base"]["metrics"], f["scenario"]["metrics"]
    if "metrics" in sections:
        keys = [k for k in base if k in scen] + [k for k in scen if k not in base]
        out.append("<h3>Base against scenario</h3>" + table(["Metric", "Base", "Scenario"], [[(base.get(k) or scen.get(k)).get("label") or k, fmt(base[k]["value"], base[k].get("unit")) if k in base else "", fmt(scen[k]["value"], scen[k].get("unit")) if k in scen else ""] for k in keys]))
    if "deltas" in sections and f["deltas"]:
        moved = [d for d in f["deltas"] if d.get("delta")]
        if moved:
            out.append("<h3>What moved</h3>" + table(["Metric", "Change", "Percent"], [[d["label"], ("+" if d["delta"] > 0 else "") + fmt(d["delta"], d.get("unit")), f"{d['pct']:+.1f}%" if d.get("pct") is not None else ""] for d in moved]))
    for key, head in (("notes", "Notes"), ("evidence", "Evidence"), ("sources", "Sources")):
        if key in sections and f.get(key):
            out.append(f"<h3>{head}</h3><ul>" + "".join(f"<li>{esc(str(x))}</li>" for x in f[key][:20]) + "</ul>")
    return "".join(out), f"Finding: {f['title'][:90]}"


def sec_brief(conn, company, opp):
    from app.crewly import brief
    b = brief.build(conn, opp)
    if not b:
        return ""
    try:
        from markdown import markdown  # optional; falls back to preformatted text
        body = markdown(b["markdown"], extensions=["tables"])
    except ImportError:
        body = f"<pre style='white-space:pre-wrap'>{esc(b['markdown'])}</pre>"
    return "<h2>Coordination brief</h2>" + body


# ---------- what people take into a call or to a commission ----------

def pair_context(conn, company, opp):
    """Both projects from our side, savings, what could be shared, plus feasibility and weather timing when they are available."""
    from app.crewly import brief
    f = brief.facts(conn, opp)
    if not f:
        raise ValueError(f"#{opp} is not one of our overlaps")
    o, a, b, s = f
    if company not in (a["org_id"], b["org_id"]):
        raise ValueError(f"#{opp} is not one of our overlaps")
    ours, theirs = (a, b) if a["org_id"] == company else (b, a)
    from app.queries import shareable
    ctx = {"o": o, "ours": ours, "theirs": theirs, "s": s, "share": shareable(o["tier"], o["a_phase"], o["b_phase"], o["drive_min"]),
           "partner": name(theirs["org_id"]), "feas": None, "haz": None}
    try:
        from app.feasibility.assess import assess
        ctx["feas"] = assess(conn, opp, company)
    except Exception:
        pass
    try:
        from app.hazards import cost as hcost
        got = hcost.for_zone(conn, opp, "month")
        ctx["haz"] = got
    except Exception:
        pass
    return ctx


def window(j):
    return f"{j['start_at']:%b %Y} to {j['end_at']:%b %Y}"


def plan_context(conn, company, horizon=None):
    """The plan a document is about: the named horizon, else the one the person saw last; built quietly when there is none."""
    from app.planner import api, build, store
    row = store.latest(conn, company, horizon) if horizon in build.HORIZONS else store.newest(conn, company)
    return row or api.rebuild(conn, company, horizon if horizon in build.HORIZONS else "quarter")


def sec_agenda(conn, company, ref, sections, options):
    opts = options or {}
    when = opts.get("when")
    out = []
    if ref.isdigit():
        c = pair_context(conn, company, int(ref))
        o, s = c["o"], c["s"]
        title = f"Coordination call: {c['ours']['name']} and {c['theirs']['name']}"
        if "context" in sections:
            out.append("<h2>Context</h2>" + table(["Utility", "Project", "Build window", "In service"],
                       [[name(company), c["ours"]["name"], window(c["ours"]), f"{c['ours']['in_service']:%b %Y}"],
                        [c["partner"], c["theirs"]["name"], window(c["theirs"]), f"{c['theirs']['in_service']:%b %Y}"]])
                       + f"<p>Closest points {o['distance_m'] / MILE_M:.1f} mi apart ({esc(o['tier'])} tier); build windows overlap {round(o['time_overlap'] * 100)}%"
                       + (f"; {o['drive_min']:.0f} min by road" if o["drive_min"] is not None else "") + f". Rough savings if scheduled together: <b>{rng(s)}</b>.</p>")
        best = [m["label"] for m in (c["haz"][1]["best_months"] if c["haz"] else [])]
        if "decisions" in sections:
            items = [f"What to share first: {', '.join(c['share'][:4])}" if c["share"] else "What to coordinate first: outage timing and access",
                     "Target months for the shared work" + (f" (weather history favors {', '.join(best)})" if best else ""),
                     "Who hosts the laydown yard and the shared standby crew", "How savings are split, and who tracks them",
                     "One contact per utility and the next check-in date"]
            out.append("<h2>Decisions to make</h2><ol>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ol>")
        if "data" in sections:
            out.append("<h2>Data each side brings</h2>" + table(["Item", name(company), c["partner"]], [
                ["Current schedule and phases", window(c["ours"]), window(c["theirs"])],
                ["Crew plan for the shared months", "to bring", "to bring"], ["Yard and access road locations", "to bring", "to bring"],
                ["Planned outage windows", "to bring", "to bring"], ["Permit status and constraints", "to bring", "to bring"]]))
        if "questions" in sections:
            qs = [cond for f in ((c["feas"] or {}).get("factors") or []) for cond in f.get("conditions", [])][:6]
            out.append("<h2>Open questions</h2><ul>" + "".join(f"<li>{esc(q)}</li>" for q in qs or ["Are both schedules still as filed?", "Which resources can each side commit?"]) + "</ul>")
    else:
        row = plan_context(conn, company, ref or None)
        items = [i for i in row["items"] if i.get("state") != "skipped"]
        title = f"Coordination call: our {row['horizon']} plan (v{row['version']})"
        t = row["totals"]
        if "context" in sections:
            out.append(f"<h2>Context</h2><p>{len(items)} pairs in the plan; expected savings <b>{rng(t['savings'])}</b>, weather cost avoided {rng(t['weather_avoided'])}.</p>"
                       + table(["Overlap", "Ours", "Partner", "Months", "Savings", "Verdict"],
                               [[f"#{i['id']}", i["ours"], i["partner_name"], f"{i['target_start'][:7]} to {i['target_end'][:7]}", rng(i["savings"]), i["verdict"]] for i in items]))
        if "decisions" in sections:
            out.append("<h2>Decisions to make</h2><ol>" + "".join(f"<li>{esc(x)}</li>" for x in [
                "Which pairs to pursue this period, and in what order", "Target months per pair", "Who hosts yards and standby crews where two pairs meet",
                "How savings are split across pairs", "Owners and the next check-in date"]) + "</ol>")
        if "data" in sections:
            out.append("<h2>Data each side brings</h2><ul><li>Current schedules and phases for every listed project</li><li>Crew and equipment availability by month</li>"
                       "<li>Yard locations and planned outage windows</li><li>Permit status per project</li></ul>")
        if "questions" in sections:
            risks = [(f"#{i['id']}", r) for i in items for r in i.get("risks", [])[:1]][:6]
            out.append("<h2>Open questions</h2><ul>" + "".join(f"<li><b>{esc(a)}:</b> {esc(str(r))}</li>" for a, r in risks) + "</ul>" if risks else "<h2>Open questions</h2><p>None flagged by the plan.</p>")
    if "logistics" in sections:
        out.append("<h2>Logistics</h2><ul>" + (f"<li>When: {esc(str(when))}</li>" if when else "<li>When: to be set</li>")
                   + "<li>Who: one transmission planner per utility, plus a construction lead if available</li><li>Follow-up: a date and an owner before the call ends</li></ul>")
    return "".join(out), title


def sec_memo(conn, company, ref, sections, options):
    audience = (options or {}).get("audience") or "internal"
    out = []
    lead = ("Prepared for review by the public service commission; public data and deterministic estimates only." if audience == "regulator"
            else "Internal working memo; estimates for assessment.")
    if ref.isdigit():
        c = pair_context(conn, company, int(ref))
        o, s = c["o"], c["s"]
        title = f"Cost-sharing memo: {c['ours']['name']} and {c['theirs']['name']}"
        if "purpose" in sections:
            out.append(f"<h2>Purpose</h2><p>{esc(lead)}</p><p>{esc(name(company))} and {esc(c['partner'])} plan work {o['distance_m'] / MILE_M:.1f} mi apart with build "
                       f"windows that overlap {round(o['time_overlap'] * 100)}%. Scheduling the work together is estimated to save <b>{rng(s)}</b>.</p>")
        if "projects" in sections:
            out.append("<h2>Projects</h2>" + table(["Utility", "Project", "Type", "Build window", "In service", "Source"],
                       [[name(company), c["ours"]["name"], c["ours"]["job_type"].replace("_", " "), window(c["ours"]), f"{c['ours']['in_service']:%b %d, %Y}", f"{c['ours']['source_title']}, p.{c['ours']['source_page']}"],
                        [c["partner"], c["theirs"]["name"], c["theirs"]["job_type"].replace("_", " "), window(c["theirs"]), f"{c['theirs']['in_service']:%b %d, %Y}", f"{c['theirs']['source_title']}, p.{c['theirs']['source_page']}"]]))
        if "savings" in sections:
            from app.config import ASSUMPTIONS
            out.append("<h2>Savings</h2>" + table(["Item", "Low", "High"], [[k, usd(v["low"]), usd(v["high"])] for k, v in s["items"].items()])
                       + "<h3>Sources</h3><ul>" + "".join(f"<li>{esc(v['label'])}: {v['low']:,} to {v['high']:,} {esc(v['unit'])}{'' if v.get('verified') else ' (estimate)'}. "
                                                         f"{esc(v['source'])}{', p.' + str(v['page']) if v.get('page') else ''}</li>" for v in ASSUMPTIONS.values() if v.get("scope") != "storm") + "</ul>")
        haz = c["haz"]
        if "timing" in sections:
            if haz:
                cst, coord = haz
                best = coord["best_months"]
                out.append("<h2>Weather and timing</h2>" + (table(["Month", "Cost per 30 days", "Saves vs the assessed month"],
                           [[m["label"], rng(m["cost_per_30d"]), rng(m["saves_vs_period"])] for m in best]) if best else "")
                           + f"<p>Expected extra cost of weather in the assessed period: {rng(cst['total'])}. {esc(cst.get('method') or '')}</p>")
            else:
                out.append("<h2>Weather and timing</h2><p>Weather cost could not be assessed for this pair.</p>")
        if "split" in sections:
            if haz:
                cst, coord = haz
                out.append("<h2>Split to agree</h2><p>Working separately costs {sep} in weather standby over the period; coordinating costs {co}, so the shared "
                           "standby is worth {sv}. The proposed principle is to split that in proportion to each utility's own expected extra cost below; the final split is for the two "
                           "utilities to agree.</p>".format(sep=rng(coord["separate"]), co=rng(coord["coordinated"]), sv=rng(coord["savings"]))
                           + table(["Site", "Expected extra cost"], [[st["name"], rng(st["total"])] for st in cst["sites"]])
                           + ("<p>One-off savings per project: " + "; ".join(f"{x['name']} {rng(x)}" for x in coord["one_off"]) + ".</p>" if coord["one_off"] else ""))
            else:
                out.append("<h2>Split to agree</h2><p>Split the estimated savings by an agreed principle once each side's costs are assessed.</p>")
        if "risks" in sections:
            f = c["feas"]
            items = [f"{x['label']}: {x['verdict']}; " + "; ".join(x["evidence"][:1] + x.get("conditions", [])[:1]) for x in ((f or {}).get("factors") or []) if x["verdict"] in ("possible", "unlikely", "unknown")]
            out.append("<h2>Risks</h2>" + (f"<p>{chip(f['verdict'])} feasibility score {f['score']:.2f}</p>" if f else "") + "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items or ["No factor was rated below strong."]) + "</ul>")
        if "next_steps" in sections:
            out.append("<h2>Next steps</h2><ol>" + "".join(f"<li>{esc(x)}</li>" for x in [
                "Confirm both schedules with each utility's engineering team", "Agree the target months and what is shared first",
                "Record the split principle and who tracks actual costs", "Revisit after the next planner list update"]) + "</ol>")
    else:
        row = plan_context(conn, company, ref or None)
        items = [i for i in row["items"] if i.get("state") != "skipped"]
        t = row["totals"]
        title = f"Cost-sharing memo: our {row['horizon']} plan (v{row['version']})"
        if "purpose" in sections:
            out.append(f"<h2>Purpose</h2><p>{esc(lead)}</p><p>{len(items)} coordinated pairs over the next {esc(row['horizon'])}; expected savings <b>{rng(t['savings'])}</b>, "
                       f"weather cost avoided by the chosen months {rng(t['weather_avoided'])}.</p>")
        if "projects" in sections:
            out.append("<h2>Projects</h2>" + table(["Overlap", "Ours", "Partner", "Their project", "Months"],
                       [[f"#{i['id']}", i["ours"], i["partner_name"], i["theirs"], f"{i['target_start'][:7]} to {i['target_end'][:7]}"] for i in items]))
        if "savings" in sections:
            out.append("<h2>Savings</h2>" + table(["Overlap", "Partner", "Savings", "Verdict"], [[f"#{i['id']}", i["partner_name"], rng(i["savings"]), i["verdict"]] for i in items]))
        if "timing" in sections:
            out.append("<h2>Weather and timing</h2><p>Each pair's months were chosen as the cheapest run inside both build windows by ten years of county weather history.</p>")
        if "split" in sections:
            out.append("<h2>Split to agree</h2><p>Per pair, in proportion to each utility's own expected extra cost; the memo for a single overlap carries those figures.</p>")
        if "risks" in sections:
            risks = [(f"#{i['id']}", r) for i in items for r in i.get("risks", [])[:2]]
            out.append("<h2>Risks</h2><ul>" + "".join(f"<li><b>{esc(a)}:</b> {esc(str(r))}</li>" for a, r in risks) + "</ul>" if risks else "<h2>Risks</h2><p>None flagged.</p>")
        if "next_steps" in sections:
            out.append("<h2>Next steps</h2><ol><li>Accept or skip each pair in the plan</li><li>Send the requests for accepted pairs</li><li>Agree splits pair by pair</li></ol>")
    return "".join(out), title


def build(conn, company, kind, ref_id=None, sections=None, options=None):
    """Render one report and store it; returns the row."""
    if kind not in KINDS:
        raise ValueError(f"unknown report kind {kind!r}; one of {', '.join(KINDS)}")
    label, default = KINDS[kind]
    sections = [s for s in (sections or []) if s in default] or default
    ref = str(ref_id or "").lstrip("#")
    who = name(company)
    if kind == "plan":
        body, title = sec_plan(conn, company, ref or None, sections), f"{label}: {who}"
    elif kind == "finding":
        body, title = sec_finding(conn, company, ref, sections)
    elif kind == "agenda":
        body, title = sec_agenda(conn, company, ref, sections, options)
    elif kind == "memo":
        body, title = sec_memo(conn, company, ref, sections, options)
    else:
        if not ref:
            raise ValueError("this report needs an overlap id like #18" + (" or a site id" if kind == "hazard_exposure" else ""))
        opp = int(ref) if ref.isdigit() else None
        if kind == "feasibility":
            body = sec_feasibility(conn, company, opp, sections)
        elif kind == "cost_analysis":
            body = sec_cost(conn, company, opp, sections)
        elif kind == "hazard_exposure":
            body = sec_hazards(conn, company, ref, sections)
        else:
            body = "".join(part for part in (
                sec_brief(conn, company, opp) if "brief" in sections else "",
                sec_feasibility(conn, company, opp, KINDS["feasibility"][1]) if "feasibility" in sections else "",
                sec_cost(conn, company, opp, KINDS["cost_analysis"][1]) if "cost_analysis" in sections else "",
                sec_hazards(conn, company, ref, KINDS["hazard_exposure"][1]) if "hazard_exposure" in sections else ""))
        title = f"{label}: {'overlap #' + ref if opp else ref}"
    doc = page(title, f"{who} · {date.today():%b %d, %Y} · crewly", body)
    conn.execute(TABLE_SQL)
    row = conn.execute("INSERT INTO report (company_id, kind, ref_id, title, sections, html) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
                       (company, kind, ref or None, title, sections, doc)).fetchone()
    return {"id": row["id"], "kind": kind, "ref_id": ref or None, "title": title, "sections": sections, "all_sections": default,
            "created_at": row["created_at"].isoformat(), "html": doc}


def get(conn, report_id, company):
    conn.execute(TABLE_SQL)
    return conn.execute("SELECT id, kind, ref_id, title, sections, html, created_at FROM report WHERE id = %s AND company_id = %s", (int(report_id), company)).fetchone()


def short_partner(company, op):
    return short(op["b_org"] if op["a_org"] == company else op["a_org"])
