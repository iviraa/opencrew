"""Printable reports Crewly can hand over: feasibility, cost analysis, hazard exposure, the plan, a pack, a finding, an agenda or a memo."""
import html
import re
from datetime import date, datetime

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
:root{--ink:#1c2230;--muted:#5b6472;--line:#e2e5ea;--soft:#f6f7f9;--accent:#2f4f8f;--good:#1f7a4d;--warn:#a05a00;--bad:#b3261e}
*{box-sizing:border-box}html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:#eef0f3;color:var(--ink);font:14px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.doc{max-width:820px;margin:32px auto 48px;padding:44px 52px 40px;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.letter{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;border-bottom:3px solid var(--ink);padding-bottom:14px;margin-bottom:22px}
.brand{font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
h1{font-size:23px;line-height:1.2;margin:8px 0 6px;font-weight:700;letter-spacing:-.01em}
.sub{font-size:13px;color:var(--muted)}.meta{font-size:12px;color:var(--muted);text-align:right;white-space:nowrap;line-height:1.7}
.summary{font-size:15px;line-height:1.65;margin:0 0 22px}
.figures{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 26px}
.fig{border:1px solid var(--line);border-radius:6px;padding:10px 12px;background:var(--soft)}
.fig .l{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}.fig .v{font-size:19px;font-weight:700;margin:3px 0 1px;line-height:1.2}.fig .n{font-size:12px;color:var(--muted)}
h2{font-size:16px;margin:26px 0 6px;padding-top:16px;border-top:1px solid var(--line)}h3{font-size:14px;margin:16px 0 4px}
p{margin:6px 0 10px}.lead{color:var(--muted);margin:0 0 8px}
table{border-collapse:collapse;width:100%;margin:8px 0 14px;font-size:13px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:2px solid var(--ink);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;width:1%}tr:last-child td{border-bottom:1px solid var(--ink)}
.chip{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600;background:var(--soft);color:var(--ink);border:1px solid var(--line)}
.chip.strong{background:#e6f4ec;color:var(--good);border-color:#bfe3cf}.chip.possible{background:#fff4e0;color:var(--warn);border-color:#f3d9a8}
.chip.unlikely{background:#fbe9e7;color:var(--bad);border-color:#f2c1bd}.chip.unknown{background:var(--soft);color:var(--muted)}
.box{border:1px solid var(--line);border-left:4px solid var(--accent);padding:10px 14px;margin:24px 0 0;background:var(--soft);font-size:13px}
.box b{display:block;margin-bottom:4px}.box ul{margin:4px 0 0;padding-left:18px}
.memo{display:grid;grid-template-columns:64px 1fr;gap:4px 12px;margin:0 0 18px;font-size:13px;border-bottom:1px solid var(--line);padding-bottom:12px}
.memo dt{font-weight:700;color:var(--muted);text-transform:uppercase;font-size:11px;letter-spacing:.06em;padding-top:2px}.memo dd{margin:0}
ol,ul{padding-left:20px}li{margin:2px 0}.pos{color:var(--good)}.neg{color:var(--bad)}.note{font-size:12px;color:var(--muted)}
footer{margin-top:36px;padding-top:10px;border-top:1px solid var(--line);font-size:11px;color:var(--muted);display:flex;justify-content:space-between;gap:16px}
.print{position:fixed;top:14px;right:14px;padding:9px 16px;border:0;border-radius:999px;background:var(--ink);color:#fff;font:600 13px inherit;cursor:pointer;box-shadow:0 2px 6px rgba(0,0,0,.2)}
@page{size:letter;margin:16mm 15mm 18mm;@bottom-right{content:"Page " counter(page) " of " counter(pages);font:10px -apple-system,Helvetica,Arial,sans-serif;color:#5b6472}}
@media print{body{background:#fff}.print{display:none}.doc{max-width:none;margin:0;padding:0;box-shadow:none}
h2,h3{page-break-after:avoid}table,tr,.fig,.box,.figures{page-break-inside:avoid}.figures{display:flex;flex-wrap:wrap}.fig{flex:1 1 140px}footer{page-break-inside:avoid}}
"""

esc = html.escape
NUM_RE = re.compile(r"^[-+]?\$?[\d.,]+\s?[kM%]?(?:\sto\s[-+]?\$?[\d.,]+\s?[kM%]?)?(?:\s(?:min|mi|days?|pts|of 1))?(?:\s\([-+]?[\d.]+%\))?$")


def txt(v):
    return "" if v is None else str(v)


def usd(n):
    n = float(n or 0)
    sign, a = ("-" if n < 0 else ""), abs(n)
    return sign + (f"${a / 1e6:.1f}M" if a >= 1e6 else f"${round(a / 1e3)}k" if a >= 1e3 else f"${round(a)}")


def rng(r):
    if isinstance(r, dict):
        return usd(r["low"]) if r.get("low") == r.get("high") else f"{usd(r['low'])} to {usd(r['high'])}"
    return usd(r)


def pct(x):
    return f"{round(float(x or 0) * 100)}%"


def mon(s):
    """'2025-03-01' or a datetime as 'Mar 2025'."""
    if not s:
        return ""
    d = s if isinstance(s, (date, datetime)) else date.fromisoformat(str(s)[:10])
    return f"{d:%b %Y}"


def span(a, b):
    """'Sep 26 to Oct 3, 2026' for two ISO dates."""
    if not a or not b:
        return ""
    a, b = date.fromisoformat(str(a)[:10]), date.fromisoformat(str(b)[:10])
    return f"{a:%b} {a.day} to {b:%b} {b.day}, {b.year}" if a.year == b.year else f"{a:%b} {a.day}, {a.year} to {b:%b} {b.day}, {b.year}"


def chip(v):
    return f'<span class="chip {esc(str(v))}">{esc(str(v).title())}</span>'


def signed(n, unit=None):
    n = float(n or 0)
    if unit == "USD":
        s = usd(n)
        return s if n <= 0 else "+" + s
    return f"{n:+g}{'%' if unit == '%' else ''}{' ' + unit if unit and unit not in ('USD', '%', 'count') else ''}"


def table(cols, rows, num=None):
    """A table with column headers; numeric-looking columns are right-aligned (or pass their indexes)."""
    rows = [[txt(c) for c in r] for r in rows]
    if num is None:
        num = {i for i in range(len(cols)) if rows and all(NUM_RE.match(r[i].strip()) for r in rows if i < len(r) and r[i].strip())
               and any(i < len(r) and r[i].strip() for r in rows)}
    cls = lambda i: ' class="num"' if i in num else ""  # noqa: E731
    head = "".join(f"<th{cls(i)}>{esc(c)}</th>" for i, c in enumerate(cols))
    body = "".join("<tr>" + "".join(f"<td{cls(i)}>{c if c.startswith('<span class=') else esc(c)}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def ul(items, ordered=False):
    tag = "ol" if ordered else "ul"
    return f"<{tag}>" + "".join(f"<li>{x if x.startswith('<b>') else esc(x)}</li>" for x in items) + f"</{tag}>"


def join(parts):
    parts = [p for p in parts if p]
    return "" if not parts else parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


class Doc:
    """What a report is made of before it becomes a page: the summary, key figures, sections and the sources behind them."""

    def __init__(self, title, subtitle=""):
        self.title, self.subtitle = title, subtitle
        self.summary, self.figures, self.parts, self.sources, self.head = [], [], [], [], ""

    def fig(self, label, value, note=""):
        if value not in (None, ""):
            self.figures.append({"label": label, "value": str(value), "note": note})

    def section(self, heading, lead, body):
        self.parts.append(f"<h2>{esc(heading)}</h2>" + (f"<p class='lead'>{esc(lead)}</p>" if lead else "") + body)

    def source(self, *xs):
        for x in xs:
            if x and x not in self.sources:
                self.sources.append(x)


def page(title, sub, body, summary="", figures=(), sources=(), head=""):
    """The self-contained page: letterhead, summary, key figures, sections, method box and footer."""
    figs = "".join(f"<div class='fig'><div class='l'>{esc(f['label'])}</div><div class='v'>{esc(f['value'])}</div><div class='n'>{esc(f.get('note') or '')}</div></div>" for f in figures)
    method = ("<div class='box'><b>Sources and method</b>Distances, days and dollar ranges come from deterministic models over public filings; nothing here is a work order."
              + (("<ul>" + "".join(f"<li>{esc(s)}</li>" for s in sources) + "</ul>") if sources else "") + "</div>")
    now = datetime.now()
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{esc(title)}</title>"
            f"<style>{CSS}</style></head><body><button class='print' onclick='window.print()'>Print / Save as PDF</button><article class='doc'>"
            f"<header class='letter'><div><div class='brand'>crewly</div><h1>{esc(title)}</h1><div class='sub'>{esc(sub)}</div></div>"
            f"<div class='meta'>{now:%B %d, %Y}<br>Prepared by crewly</div></header>{head}"
            + (f"<p class='summary'>{esc(summary)}</p>" if summary else "") + (f"<div class='figures'>{figs}</div>" if figs else "") + body + method
            + f"<footer><span>crewly · assessment only, not a work order</span><span>Generated {now:%b %d, %Y %H:%M}</span></footer></article></body></html>")


# ---------- shared lookups ----------

def overlap(conn, company, opp):
    from app.queries import OPP_SQL
    op = conn.execute(OPP_SQL + " WHERE op.id = %s", (opp,)).fetchone() if opp else None
    if not op or company not in (op["a_org"], op["b_org"]):
        raise ValueError(f"#{opp} is not one of our overlaps")
    mine = op["a_org"] == company
    return {"op": op, "ours": op["a_name" if mine else "b_name"], "theirs": op["b_name" if mine else "a_name"], "partner_id": op["b_org" if mine else "a_org"],
            "partner": name(op["b_org" if mine else "a_org"]), "our_window": (op["a_start" if mine else "b_start"], op["a_end" if mine else "b_end"]),
            "their_window": (op["b_start" if mine else "a_start"], op["b_end" if mine else "a_end"])}


def pair_line(c):
    """One sentence that places the pair: projects, partner, tier, distance, shared window."""
    op = c["op"]
    drive = f", {op['drive_min']:.0f} minutes apart by road" if op["drive_min"] is not None else ""
    return (f"Overlap #{op['id']} pairs our {c['ours']} with {short(c['partner_id'])}'s {c['theirs']}: a {op['tier']}-tier overlap with closest points "
            f"{op['distance_m'] / MILE_M:.1f} miles apart{drive}, and build windows that share {pct(op['time_overlap'])} of their time "
            f"(ours {mon(c['our_window'][0])} to {mon(c['our_window'][1])}, theirs {mon(c['their_window'][0])} to {mon(c['their_window'][1])}).")


# ---------- sections ----------

def sec_feasibility(conn, company, opp, sections, d):
    from app.feasibility.assess import assess
    a = assess(conn, opp, company)
    if not a:
        raise ValueError(f"#{opp} is not one of our overlaps")
    c = overlap(conn, company, opp)
    op = c["op"]
    d.subtitle = d.subtitle or f"{name(company)} with {c['partner']} · overlap #{opp}"
    d.summary.append(pair_line(c) + " " + txt(a.get("narrative")))
    d.fig("Verdict", str(a["verdict"]).title(), f"score {a['score']:.2f} of 1")
    if op["savings_high"]:
        d.fig("Savings if coordinated", rng({"low": op["savings_low"], "high": op["savings_high"]}), "one-off items paid once")
    d.fig("Shared build window", pct(op["time_overlap"]), "of the shorter window")
    d.fig("Distance", f"{op['distance_m'] / MILE_M:.1f} mi", f"{op['drive_min']:.0f} min by road" if op["drive_min"] is not None else f"{op['tier']} tier")
    factors = a["factors"]
    if "factors" in sections:
        rows = [[f["label"], chip(f["verdict"]), cap("; ".join(f["evidence"][:3])) + ("." if f["evidence"] else "")] for f in factors]
        d.section("Factors", "Seven factors, weighted by how much they decide a coordination; one factor rated unlikely caps the verdict, two make it unlikely.",
                  table(["Factor", "Verdict", "Evidence"], rows, num=set()))
    if "conditions" in sections:
        conds = [f"<b>{esc(f['label'])}:</b> {esc(x[0].upper() + x[1:])}." for f in factors for x in f.get("conditions", [])[:2]]
        if conds:
            d.section("What would make it work", "Conditions raised by the factors that were not rated strong.", ul(conds))
    if "shifts" in sections:
        opts = next((f.get("options") for f in factors if f.get("options")), None)
        if opts:
            rows = [[f"{o['months']:+d} month{'s' if abs(o['months']) != 1 else ''}", pct(o["overlap"]), f"{round(o['overlap_delta'] * 100):+d} pts",
                     rng(o["weather_cost_delta"]) if o.get("weather_cost_delta") else "not assessed"] for o in opts]
            d.section("If our window moved", "How much of the shorter window the two projects would share if our build window shifted, and what the weather would cost or save.",
                      table(["Shift", "Shared window", "Change", "Weather cost change"], rows))
    d.source(*[s for f in factors for s in f.get("sources", [])])


def sec_cost(conn, company, opp, sections, d):
    from app.engine.cost import savings_for
    from app.hazards import cost
    c = overlap(conn, company, opp)
    op = c["op"]
    d.subtitle = d.subtitle or f"{name(company)} with {c['partner']} · overlap #{opp}"
    s = savings_for(conn, op)
    top = sorted(s["items"].items(), key=lambda kv: -float(kv[1]["high"]))[:2]
    got = cost.for_zone(conn, opp, "month") if {"weather", "coordination"} & set(sections) else None
    d.summary.append(pair_line(c) + f" Scheduling the two together is estimated to save {rng(s)} in one-off costs, mostly from {join([k.lower() for k, _ in top])}.")
    d.fig("One-off savings", rng(s), "paid once instead of twice")
    if top:
        d.fig("Largest item", rng(top[0][1]), top[0][0])
    if "savings" in sections:
        d.section("Savings from coordinating", "Costs both utilities would otherwise pay separately; each line is a low-to-high range.",
                  table(["Item", "Low", "High"], [[k, usd(v["low"]), usd(v["high"])] for k, v in s["items"].items()] + [["Total", usd(s["low"]), usd(s["high"])]]))
    if got:
        cst, coord = got
        best = coord.get("best_months") or []
        d.summary.append(f"In a typical {mon(cst['start'])}, weather adds {rng(cst['total'])} across both sites; sharing standby on the days both sites are affected "
                         f"trims that to {rng(coord['coordinated'])}" + (f", and {join([m['label'] for m in best])} are the cheapest months to work the pair." if best else "."))
        d.fig("Weather cost, typical month", rng(cst["total"]), "both sites, expected extra cost")
        d.fig("Shared standby savings", rng(coord["savings"]), "on days both sites are affected")
        if "weather" in sections:
            rows = [[site["name"], i["label"], f"{i['days']['low']:g} to {i['days']['high']:g}", rng(i["total"])] for site in cst["sites"] for i in site["items"]]
            d.section(f"Weather in a typical {mon(cst['start'])}", "Expected affected days per hazard from county history, priced at the cheaper of standby and demobilizing.",
                      table(["Site", "Hazard", "Affected days", "Expected cost"], rows))
        if "coordination" in sections:
            body = (f"<p>Working separately, weather standby costs {rng(coord['separate'])} over the period; working together it costs {rng(coord['coordinated'])}, "
                    f"so the shared standby is worth <b>{rng(coord['savings'])}</b>.</p>")
            if best:
                body += table(["Cheapest months", "Cost per 30 days", "Saves against this period"], [[m["label"], rng(m["cost_per_30d"]), rng(m["saves_vs_period"])] for m in best])
            d.section("Coordinating with the neighbor", "Shared standby on the days both sites are affected, and the months weather history favors.", body)
        d.source(cst["method"], "Cost assumptions: " + ", ".join(cst.get("assumptions", [])))
    d.source("crewly cost-savings model over the filed project costs and windows")


def sec_hazards(conn, company, ident, sections, d):
    from app.hazards.exposure import assess
    kind = "zone" if str(ident).isdigit() else "site"
    labels = {"now7": "Next 7 days", "season": "Next season", "month": "Typical month"}
    first = True
    for p in ("now7", "season", "month"):
        if p not in sections:
            continue
        e = assess(conn, kind, ident, p)
        if not e:
            raise ValueError(f"no {kind} {ident}")
        if first:
            d.subtitle = d.subtitle or f"{name(company)} · {join(e['names'][:2])}"
            lead = e["hazards"][0] if e["hazards"] else None
            d.summary.append(f"This assessment covers {join(e['names'][:2])} across {e['counties']} count{'y' if e['counties'] == 1 else 'ies'}."
                             + (f" The leading hazard is {lead['label'].lower()}, which affects {lead['why']}." if lead else ""))
            first = False
        t = e["affected_days"]
        days = f"{t['forecast']:g} forecast" if p == "now7" else f"{t['low']:g} to {t['high']:g}"
        d.fig(labels[p], f"{days} days", f"{mon(e['start'])} to {mon(e['end'])}" if p != "now7" else "days with an active alert or outlook")
        d.summary.append(f"{labels[p]}, {span(e['start'], e['end'])}: " + (f"{t['forecast']:g} affected days in the forecast." if p == "now7"
                         else f"history suggests {t['low']:g} to {t['high']:g} affected days."))
        rows = [[h["label"], f"{h['affected_days'].get('forecast', 0):g}", f"{h['affected_days'].get('low', 0):g} to {h['affected_days'].get('high', 0):g}",
                 ", ".join(x["label"] for x in h.get("live", [])[:2]) or "none", h["why"]] for h in e["hazards"]]
        d.section(f"{labels[p]}: {span(e['start'], e['end'])}", "Affected days by hazard; forecast days count active alerts and outlooks, history is the county record.",
                  table(["Hazard", "Forecast days", "History", "Active now", "Work it affects"], rows, num={1, 2}))
        d.source(e.get("method"))


def sec_plan(conn, company, horizon, sections, d):
    row = plan_context(conn, company, horizon)
    t, items = row["totals"], row["items"]
    live = [i for i in items if i.get("state") != "skipped"]
    label = {"quarter": "next quarter", "year": "next year", "window": "whole build windows"}.get(row["horizon"], row["horizon"])
    d.subtitle = d.subtitle or f"{name(company)} · {label} · version {row['version']}"
    v = t.get("verdicts") or {}
    d.summary.append(f"The plan for the {label} selects {len(items)} pairs out of {t.get('considered', len(items))} considered, worth {rng(t['savings'])} if every pair proceeds. "
                     + (f"Working each pair in its cheapest months avoids {rng(t['weather_avoided'])} of weather cost. " if float(t['weather_avoided'].get('high') or 0) > 0 else "")
                     + join([f"{n} rated {k}" for k, n in v.items() if n]) + "." + (f" {t['note']}" if t.get("note") else ""))
    if t.get("passed"):
        d.summary.append(f"{t['passed']} pair{'s' if t['passed'] != 1 else ''} rest on filed windows that have already ended, so those dates need confirming before any outreach.")
    d.fig("Pairs", len(items), f"{len(live)} in play, {len(items) - len(live)} skipped")
    d.fig("Expected savings", rng(t["savings"]), "if every pair proceeds")
    if float(t["weather_avoided"].get("high") or 0) > 0:
        d.fig("Weather cost avoided", rng(t["weather_avoided"]), "by the chosen months")
    if t.get("conflicts"):
        d.fig("Conflicts", t["conflicts"], "pairs sharing a crew or month")
    acc = sum(1 for i in items if i.get("state") == "accepted")
    d.fig("Accepted", acc, "by the planner so far")
    if "items" in sections:
        rows = [[f"#{i['id']}", i["ours"], f"{i['theirs']} ({i['partner_short']})", f"{mon(i['target_start'])} to {mon(i['target_end'])}", rng(i["savings"]),
                 chip(i["verdict"]), i["state"].replace("_", " ")] for i in items]
        d.section("Pairs", "Each pair with its partner, the target months chosen by weather history, and the expected savings.",
                  table(["Overlap", "Our project", "Partner project", "Target months", "Savings", "Verdict", "Status"], rows, num={4}))
    if "risks" in sections:
        risks = [f"<b>#{esc(i['id'])}:</b> {esc(str(r)[0].upper() + str(r)[1:])}" for i in items for r in i.get("risks", [])[:2]]
        if risks:
            d.section("Risks", "Flags raised per pair by the feasibility factors and recent news.", ul(risks[:24]))
    sk = t.get("skipped") or {}
    if isinstance(sk, dict) and sk:
        d.parts.append("<p class='note'>Not selected: " + join([f"{n} {k}" for k, n in sk.items()]) + ".</p>")
    d.source("planner lists as filed", "feasibility assessment per pair", "ten years of county weather history for the month choice")


def describe_change(kind, params):
    """One plain sentence for a scenario change."""
    p = {k: v for k, v in params.items() if k != "base_finding_id"}
    who = lambda k: name(str(p.get(k))) if p.get(k) else ""  # noqa: E731
    ref = f"overlap #{p['opportunity_id']}" if p.get("opportunity_id") else f"project {p['job_id']}" if p.get("job_id") else "the pair"
    if kind == "shift_window":
        m = int(p.get("months") or 0)
        return f"Move our build window on {ref} {'later' if m >= 0 else 'earlier'} by {abs(m)} month{'s' if abs(m) != 1 else ''}."
    if kind == "exclude_partner":
        return f"Leave {who('partner') or 'that partner'} out of the plan."
    if kind == "swap_partner":
        return f"Pair the project with {who('partner') or 'another partner'} instead."
    if kind == "storm":
        where = p.get("place") if isinstance(p.get("place"), str) else (p.get("place") or {}).get("label") if isinstance(p.get("place"), dict) else None
        return f"A category {p.get('category', 3)} storm" + (f" over {where}" if where else " over the works") + "."
    if kind == "replay_year":
        return f"Replay the weather of {p.get('year', '')}."
    if kind == "event":
        return f"Apply the historical event {str(p.get('name') or p.get('event') or '').title()}."
    if kind == "assumption":
        return "Change the cost assumptions: " + ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in p.items() if k not in ("opportunity_id", "job_id")) + "."
    if kind == "capacity":
        return f"Add {p.get('crews_extra', p.get('crews', ''))} extra crew(s)" + (f" in {p['quarter']}" if p.get("quarter") else "") + "."
    if kind == "budget":
        return f"Cap the budget at {usd(p.get('budget') or p.get('usd') or 0)}."
    if kind == "cancel_project":
        return f"Cancel {ref}."
    if kind == "add_project":
        return f"Add a new project{': ' + str(p['name']) if p.get('name') else ''}."
    if kind == "sensitivity":
        return f"Vary {str(p.get('knob') or p.get('assumption') or 'one assumption').replace('_', ' ')} across its range."
    if kind == "best_windows":
        return f"Search for the cheapest months to work {ref}."
    if kind == "rule":
        return f"Apply the rule: {p.get('rule') or p.get('text') or ''}."
    return kind.replace("_", " ").capitalize() + (": " + ", ".join(f"{k} {v}" for k, v in p.items()) if p else "") + "."


def cap(x):
    x = txt(x).strip()
    return x[0].upper() + x[1:] if x else x


def merged_metrics(base, scen, deltas):
    """Metric rows with a metric's low and high halves folded into one range row; the movers carry a change and a percent."""
    by = {x["metric"]: x for x in deltas}
    keys = [k for k in base if k in scen] + [k for k in scen if k not in base]
    rows, seen = [], set()
    for k in keys:
        if k in seen:
            continue
        stem = k[:-4] if k.endswith("_low") else k[:-5] if k.endswith("_high") else None
        lo, hi = (stem + "_low", stem + "_high") if stem else (None, None)
        m = base.get(k) or scen.get(k)
        u = m.get("unit")
        val = lambda src, key: src[key]["value"] if key in src else None  # noqa: E731
        if stem and lo in keys and hi in keys:
            seen.update({lo, hi})
            r = lambda src: (f"{fmt_metric(val(src, lo), u)} to {fmt_metric(val(src, hi), u)}" if u in ("USD", "%", "count", None) else f"{val(src, lo):g} to {val(src, hi):g} {u}")  # noqa: E731
            dl, dh = by.get(lo, {}), by.get(hi, {})
            moved = bool(dl.get("delta") or dh.get("delta"))
            pcts = [x["pct"] for x in (dl, dh) if x.get("pct") is not None]
            rows.append({"label": cap(m.get("label") or k).replace(" (low)", "").replace(" (high)", ""), "base": r(base), "scenario": r(scen), "moved": moved,
                         "change": (f"{signed(dl.get('delta') or 0, u)} to {signed(dh.get('delta') or 0, u)}" if moved else "no change"),
                         "pct": (max(pcts, key=abs) if pcts else None) if moved else None, "delta": dh.get("delta") or dl.get("delta") or 0, "unit": u})
        else:
            seen.add(k)
            dl = by.get(k, {})
            moved = bool(dl.get("delta"))
            rows.append({"label": cap(m.get("label") or k), "base": fmt_metric(val(base, k), u) if k in base else "", "scenario": fmt_metric(val(scen, k), u) if k in scen else "",
                         "moved": moved, "change": signed(dl["delta"], u) if moved else "no change", "pct": dl.get("pct") if moved else None, "delta": dl.get("delta") or 0, "unit": u})
    return rows


def fmt_metric(v, unit):
    if isinstance(v, bool) or v is None:
        return txt(v)
    if isinstance(v, (int, float)):
        if unit == "USD":
            return usd(v)
        if unit == "%":
            return f"{v:g}%"
        if unit in ("count", None):
            return f"{v:g}"
        return f"{v:g} {unit}"
    return str(v)


def sec_finding(conn, company, ref, sections, d):
    """One experiment: the question, what was changed, base against scenario, and what moved."""
    from app.scenario import experiments
    f = experiments.get(conn, int(ref), company) if str(ref).isdigit() else None
    if not f:
        raise ValueError("this report needs a finding id")
    d.title = "Finding: " + re.sub(r"\b1 month\(s\)", "1 month", f["title"][:90]).replace("month(s)", "months")
    d.subtitle = d.subtitle or f"{name(company)} · what-if experiment #{ref}"
    changes = f["params"].get("changes") if f["kind"] == "compose" else [{"kind": f["kind"], "params": {k: v for k, v in f["params"].items() if k != "changes"}}]
    sentences = [describe_change(c["kind"], c.get("params") or {}) for c in (changes or [])]
    rows = merged_metrics(f["base"]["metrics"], f["scenario"]["metrics"], f["deltas"])
    moved = sorted([r for r in rows if r["moved"]], key=lambda r: -abs(r["pct"] or 0))
    verdict = next((x for x in f["deltas"] if x["metric"] == "verdict"), None)
    q = txt(f.get("question")).strip()
    lead = (q + " " if q and q.endswith("?") else "") + "The experiment " + ("stacks " + str(len(sentences)) + " changes: " if len(sentences) > 1 else "makes one change: ") \
        + ", then ".join(s[0].lower() + s[1:].rstrip(".") for s in sentences) + "."
    if moved:
        m = moved[0]
        lead += f" Against the base, {m['label'][0].lower() + m['label'][1:]} moves from {m['base']} to {m['scenario']}" + (f" ({m['pct']:+.0f}%)" if m["pct"] is not None else "") \
                + (f", with {len(moved) - 1} other metric{'s' if len(moved) > 2 else ''} changing." if len(moved) > 1 else ".")
    else:
        lead += " No tracked metric moves."
    if verdict:
        lead += (f" The feasibility verdict stays {verdict['base']}." if verdict["base"] == verdict["scenario"] else f" The feasibility verdict goes from {verdict['base']} to {verdict['scenario']}.")
    d.summary.append(lead)
    for m in moved[:3 if verdict else 4]:
        d.fig(m["label"], m["scenario"], f"was {m['base']}" + (f", {m['pct']:+.0f}%" if m["pct"] is not None else ""))
    if verdict:
        d.fig("Feasibility verdict", str(verdict["scenario"]).title(), "unchanged" if verdict["base"] == verdict["scenario"] else f"was {verdict['base']}")
    if "stack" in sections and sentences:
        d.section("What was changed", "", ul(sentences, ordered=len(sentences) > 1))
    if "metrics" in sections:
        d.section("Base against scenario", "Every tracked metric before and after the change; paired low and high estimates are shown as ranges.",
                  table(["Metric", "Base", "Scenario", "Change"], [[r["label"], r["base"], r["scenario"], r["change"] + (f" ({r['pct']:+.0f}%)" if r["pct"] else "")] for r in rows], num={1, 2, 3}))
    if "deltas" in sections and moved:
        why = [f"{m['label']} {'rises' if m['delta'] > 0 else 'falls'} by {m['change'].replace('+', '').replace('-', '')}" + (f" ({m['pct']:+.0f}%)" if m["pct"] is not None else "") for m in moved[:5]]
        notes = [cap(n).rstrip(".") + "." for n in (f.get("notes") or []) if n][:3]
        d.section("What moved and why", "", f"<p>{esc(join(why))}.</p>" + (f"<p>{esc(' '.join(notes))}</p>" if notes else ""))
    for key, head in (("notes", "Notes"), ("evidence", "Evidence")):
        if key in sections and f.get(key) and not (key == "notes" and "deltas" in sections and moved):
            d.section(head, "", ul([cap(x) for x in f[key][:20]]))
    d.source(*(f.get("sources") or []))


def sec_brief(conn, company, opp, d):
    from app.crewly import brief
    b = brief.build(conn, opp)
    if not b:
        return
    try:
        from markdown import markdown  # optional; falls back to preformatted text
        body = markdown(b["markdown"], extensions=["tables"])
    except ImportError:
        body = f"<pre style='white-space:pre-wrap'>{esc(b['markdown'])}</pre>"
    d.section("Coordination brief", "", body)


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
        ctx["haz"] = hcost.for_zone(conn, opp, "month")
    except Exception:
        pass
    return ctx


def window(j):
    return f"{mon(j['start_at'])} to {mon(j['end_at'])}"


def source_of(j):
    return txt(j.get("source_title")) + (f", p. {j['source_page']}" if j.get("source_page") else "")


def in_service(j):
    return f"{j['in_service']:%b %Y}" if j.get("in_service") else "not filed"


def plan_context(conn, company, horizon=None):
    """The plan a document is about: the named horizon, else the one the person saw last; built quietly when there is none."""
    from app.planner import api, build, store
    row = store.latest(conn, company, horizon) if horizon in build.HORIZONS else store.newest(conn, company)
    return row or api.rebuild(conn, company, horizon if horizon in build.HORIZONS else "quarter")


def plan_label(row):
    return {"quarter": "next quarter", "year": "next year", "window": "whole build windows"}.get(row["horizon"], row["horizon"])


def sec_agenda(conn, company, ref, sections, options, d):
    opts = options or {}
    when = opts.get("when")
    slots = [(s, mins) for s, mins in (("context", 10), ("decisions", 20), ("data", 10), ("questions", 10), ("logistics", 5)) if s in sections]
    titles = {"context": "Where the projects stand", "decisions": "Decisions to make", "data": "Data each side brings", "questions": "Open questions", "logistics": "Logistics and follow-up"}
    t0, rows = 0, []
    for s, mins in slots:
        rows.append([f"{t0} min", titles[s], f"{mins} min"])
        t0 += mins
    if ref.isdigit():
        c = pair_context(conn, company, int(ref))
        o, s = c["o"], c["s"]
        d.title = f"Coordination call: {c['ours']['name']} and {c['theirs']['name']}"
        d.subtitle = f"{name(company)} with {c['partner']} · overlap #{ref}" + (f" · {when}" if when else "")
        best = [m["label"] for m in (c["haz"][1]["best_months"] if c["haz"] else [])]
        d.summary.append(f"A {t0}-minute call between {name(company)} and {c['partner']} on overlap #{ref}: our {c['ours']['name']} and their {c['theirs']['name']}, "
                         f"{o['distance_m'] / MILE_M:.1f} miles apart with build windows that share {pct(o['time_overlap'])} of their time. "
                         f"Scheduling the work together is estimated to save {rng(s)}" + (f"; weather history favors {join(best)}." if best else "."))
        d.fig("Savings at stake", rng(s), "if scheduled together")
        d.fig("Shared window", pct(o["time_overlap"]), "of the shorter window")
        if c["feas"]:
            d.fig("Feasibility", str(c["feas"]["verdict"]).title(), f"score {c['feas']['score']:.2f} of 1")
        if best:
            d.fig("Best months", join(best), "by weather history")
        d.section("Agenda", "", table(["Start", "Item", "Length"], rows, num=set()))
        if "context" in sections:
            d.section(titles["context"], "Both projects as filed, from our side.",
                      table(["Utility", "Project", "Build window", "In service"], [[name(company), c["ours"]["name"], window(c["ours"]), in_service(c["ours"])],
                                                                                   [c["partner"], c["theirs"]["name"], window(c["theirs"]), in_service(c["theirs"])]], num=set())
                      + (f"<p>What could be shared first: {join(c['share'][:4])}.</p>" if c["share"] else ""))
        if "decisions" in sections:
            items = [f"What to share first: {join(c['share'][:4])}." if c["share"] else "What to coordinate first: outage timing and site access.",
                     "Target months for the shared work" + (f"; weather history favors {join(best)}." if best else "."),
                     "Who hosts the laydown yard and the shared standby crew.", "How savings are split, and who tracks actual costs.",
                     "One contact per utility and the next check-in date."]
            d.section(titles["decisions"], "", ul(items, ordered=True))
        if "data" in sections:
            d.section(titles["data"], "", table(["Item", name(company), c["partner"]], [
                ["Current schedule and phases", window(c["ours"]), window(c["theirs"])],
                ["Crew plan for the shared months", "to bring", "to bring"], ["Yard and access road locations", "to bring", "to bring"],
                ["Planned outage windows", "to bring", "to bring"], ["Permit status and constraints", "to bring", "to bring"]], num=set()))
        if "questions" in sections:
            qs = [x[0].upper() + x[1:] + "." for f in ((c["feas"] or {}).get("factors") or []) for x in f.get("conditions", [])][:6]
            d.section(titles["questions"], "Raised by the feasibility factors that were not rated strong." if qs else "",
                      ul(qs or ["Are both schedules still as filed?", "Which resources can each side commit?"]))
    else:
        row = plan_context(conn, company, ref or None)
        items = [i for i in row["items"] if i.get("state") != "skipped"]
        t = row["totals"]
        d.title = f"Coordination call: our plan for the {plan_label(row)}"
        d.subtitle = f"{name(company)} · plan version {row['version']}" + (f" · {when}" if when else "")
        d.summary.append(f"A {t0}-minute review of the {len(items)} pairs in our plan for the {plan_label(row)}, worth {rng(t['savings'])} if every pair proceeds"
                         + (f" and avoiding {rng(t['weather_avoided'])} of weather cost through the chosen months." if float(t["weather_avoided"].get("high") or 0) > 0 else ".")
                         + " The call settles which pairs to pursue, in what order, and who owns each one.")
        d.fig("Pairs to review", len(items), "not yet skipped")
        d.fig("Savings at stake", rng(t["savings"]), "if every pair proceeds")
        d.section("Agenda", "", table(["Start", "Item", "Length"], rows, num=set()))
        if "context" in sections:
            d.section(titles["context"], "Every pair in the plan with its target months.",
                      table(["Overlap", "Our project", "Partner", "Target months", "Savings", "Verdict"],
                            [[f"#{i['id']}", i["ours"], i["partner_name"], f"{mon(i['target_start'])} to {mon(i['target_end'])}", rng(i["savings"]), chip(i["verdict"])] for i in items], num={4}))
        if "decisions" in sections:
            d.section(titles["decisions"], "", ul(["Which pairs to pursue this period, and in what order.", "Target months per pair.",
                                                    "Who hosts yards and standby crews where two pairs meet.", "How savings are split across pairs.",
                                                    "Owners and the next check-in date."], ordered=True))
        if "data" in sections:
            d.section(titles["data"], "", ul(["Current schedules and phases for every listed project.", "Crew and equipment availability by month.",
                                               "Yard locations and planned outage windows.", "Permit status per project."]))
        if "questions" in sections:
            risks = [f"<b>#{esc(i['id'])}:</b> {esc(str(r)[0].upper() + str(r)[1:])}" for i in items for r in i.get("risks", [])[:1]][:6]
            d.section(titles["questions"], "", ul(risks) if risks else "<p>None flagged by the plan.</p>")
    if "logistics" in sections:
        d.section(titles["logistics"], "", ul([f"When: {when}." if when else "When: to be set.",
                                                "Who: one transmission planner per utility, plus a construction lead if available.",
                                                "Follow-up: a date and an owner agreed before the call ends."]))
    d.source("planner lists as filed", "crewly cost-savings model", "feasibility assessment", "county weather history")


def memo_head(to, frm, re_, date_=None):
    return ("<dl class='memo'>" + "".join(f"<dt>{k}</dt><dd>{esc(v)}</dd>" for k, v in (("To", to), ("From", frm), ("Date", f"{date_ or date.today():%B %d, %Y}"), ("Re", re_))) + "</dl>")


def sec_memo(conn, company, ref, sections, options, d):
    audience = (options or {}).get("audience") or "internal"
    to = "Public Service Commission staff" if audience == "regulator" else "Transmission planning leadership"
    frm = f"{name(company)} transmission planning, prepared with crewly"
    lead = ("Prepared for review by the public service commission, from public filings and deterministic estimates." if audience == "regulator" else "Internal working memo; estimates for assessment, not commitments.")
    if ref.isdigit():
        c = pair_context(conn, company, int(ref))
        o, s = c["o"], c["s"]
        d.title = f"Cost-sharing memo: {c['ours']['name']} and {c['theirs']['name']}"
        d.subtitle = f"{name(company)} with {c['partner']} · overlap #{ref}"
        d.head = memo_head(to, frm, f"Sharing costs on overlap #{ref} with {c['partner']}")
        haz = c["haz"]
        d.summary.append(f"{lead} {name(company)} and {c['partner']} plan work {o['distance_m'] / MILE_M:.1f} miles apart with build windows that share {pct(o['time_overlap'])} "
                         f"of their time. Scheduling the two together is estimated to save {rng(s)} in one-off costs"
                         + (f", and a shared standby on weather days a further {rng(haz[1]['savings'])} in a typical month." if haz else "."))
        d.fig("One-off savings", rng(s), "paid once instead of twice")
        if haz:
            d.fig("Shared standby", rng(haz[1]["savings"]), "typical month")
        if c["feas"]:
            d.fig("Feasibility", str(c["feas"]["verdict"]).title(), f"score {c['feas']['score']:.2f} of 1")
        d.fig("Shared window", pct(o["time_overlap"]), "of the shorter window")
        if "purpose" in sections:
            d.section("Purpose", "", f"<p>This memo sets out the savings available if {name(company)} and {c['partner']} schedule the two projects together, "
                                     "how the timing could be chosen, and a principle for splitting the shared costs.</p>")
        if "projects" in sections:
            d.section("Projects", "As filed with the regional planner.",
                      table(["Utility", "Project", "Type", "Build window", "In service", "Source"],
                            [[name(company), c["ours"]["name"], c["ours"]["job_type"].replace("_", " "), window(c["ours"]), in_service(c["ours"]), source_of(c["ours"])],
                             [c["partner"], c["theirs"]["name"], c["theirs"]["job_type"].replace("_", " "), window(c["theirs"]), in_service(c["theirs"]), source_of(c["theirs"])]], num=set()))
        if "savings" in sections:
            from app.config import ASSUMPTIONS
            d.section("Savings", "One-off costs both utilities would otherwise pay separately.",
                      table(["Item", "Low", "High"], [[k, usd(v["low"]), usd(v["high"])] for k, v in s["items"].items()] + [["Total", usd(s["low"]), usd(s["high"])]]))
            d.source(*[f"{v['label']}: {v['low']:,} to {v['high']:,} {v['unit']}{'' if v.get('verified') else ' (estimate)'}; {v['source']}{', p. ' + str(v['page']) if v.get('page') else ''}"
                       for v in ASSUMPTIONS.values() if v.get("scope") != "storm"])
        if "timing" in sections:
            if haz:
                cst, coord = haz
                best = coord["best_months"]
                body = (f"<p>In a typical {mon(cst['start'])}, weather is expected to add {rng(cst['total'])} across both sites." + (f" The cheapest months to work the pair by ten years of county history are {join([m['label'] for m in best])}.</p>" if best else "</p>")
                        + (table(["Month", "Cost per 30 days", "Saves against the assessed month"], [[m["label"], rng(m["cost_per_30d"]), rng(m["saves_vs_period"])] for m in best]) if best else ""))
                d.section("Weather and timing", "", body)
                d.source(cst.get("method"))
            else:
                d.section("Weather and timing", "", "<p>Weather cost could not be assessed for this pair.</p>")
        if "split" in sections:
            if haz:
                cst, coord = haz
                body = (f"<p>Working separately, weather standby costs {rng(coord['separate'])} over the period; coordinating costs {rng(coord['coordinated'])}, so the shared standby is worth "
                        f"<b>{rng(coord['savings'])}</b>. The proposed principle splits that in proportion to each utility's own expected extra cost below; the final split is for the two utilities to agree.</p>"
                        + table(["Site", "Expected extra cost"], [[st["name"], rng(st["total"])] for st in cst["sites"]])
                        + (f"<p>One-off savings per project: {join([f'{x['name'].lower()} {rng(x)}' for x in coord['one_off']])}.</p>" if coord["one_off"] else ""))
                d.section("Split to agree", "", body)
            else:
                d.section("Split to agree", "", "<p>Split the estimated savings by an agreed principle once each side's costs are assessed.</p>")
        if "risks" in sections:
            f = c["feas"]
            items = [f"<b>{esc(x['label'])} ({esc(x['verdict'])}):</b> " + esc(cap("; ".join(x["evidence"][:1] + x.get("conditions", [])[:1])) + ".")
                     for x in ((f or {}).get("factors") or []) if x["verdict"] in ("possible", "unlikely", "unknown")]
            d.section("Risks", f"Feasibility is rated {f['verdict']} (score {f['score']:.2f} of 1)." if f else "", ul(items or ["No factor was rated below strong."]))
        if "next_steps" in sections:
            d.section("Next steps", "", ul(["Confirm both schedules with each utility's engineering team.", "Agree the target months and what is shared first.",
                                            "Record the split principle and who tracks actual costs.", "Revisit after the next planner list update."], ordered=True))
    else:
        row = plan_context(conn, company, ref or None)
        items = [i for i in row["items"] if i.get("state") != "skipped"]
        t = row["totals"]
        d.title = f"Cost-sharing memo: our plan for the {plan_label(row)}"
        d.subtitle = f"{name(company)} · plan version {row['version']}"
        d.head = memo_head(to, frm, f"Sharing costs across the {len(items)} pairs in our {plan_label(row)} plan")
        d.summary.append(f"{lead} The plan holds {len(items)} coordinated pairs over the {plan_label(row)}, worth {rng(t['savings'])} if every pair proceeds"
                         + (f", with {rng(t['weather_avoided'])} of weather cost avoided by the chosen months." if float(t["weather_avoided"].get("high") or 0) > 0 else "."))
        d.fig("Pairs", len(items), "in the plan")
        d.fig("Expected savings", rng(t["savings"]), "if every pair proceeds")
        if float(t["weather_avoided"].get("high") or 0) > 0:
            d.fig("Weather cost avoided", rng(t["weather_avoided"]), "by the chosen months")
        if "purpose" in sections:
            d.section("Purpose", "", "<p>This memo lists the pairs in the plan, what each is worth, how their months were chosen, and the principle proposed for splitting shared costs pair by pair.</p>")
        if "projects" in sections:
            d.section("Projects", "", table(["Overlap", "Our project", "Partner", "Partner project", "Target months"],
                                            [[f"#{i['id']}", i["ours"], i["partner_name"], i["theirs"], f"{mon(i['target_start'])} to {mon(i['target_end'])}"] for i in items], num=set()))
        if "savings" in sections:
            d.section("Savings", "", table(["Overlap", "Partner", "Savings", "Verdict"], [[f"#{i['id']}", i["partner_name"], rng(i["savings"]), chip(i["verdict"])] for i in items], num={2}))
        if "timing" in sections:
            d.section("Weather and timing", "", "<p>Each pair's months are the cheapest run inside both build windows by ten years of county weather history.</p>")
        if "split" in sections:
            d.section("Split to agree", "", "<p>Per pair, in proportion to each utility's own expected extra cost; the memo for a single overlap carries those figures.</p>")
        if "risks" in sections:
            risks = [f"<b>#{esc(i['id'])}:</b> {esc(str(r)[0].upper() + str(r)[1:])}" for i in items for r in i.get("risks", [])[:2]]
            d.section("Risks", "", ul(risks) if risks else "<p>None flagged.</p>")
        if "next_steps" in sections:
            d.section("Next steps", "", ul(["Accept or skip each pair in the plan.", "Send the requests for accepted pairs.", "Agree splits pair by pair."], ordered=True))
    d.source("planner lists as filed", "crewly cost-savings model", "feasibility assessment", "county weather history")


def compose(conn, company, kind, ref_id=None, sections=None, options=None):
    """Assemble a report without storing it: the Doc, the resolved sections and the plain-text summary."""
    if kind not in KINDS:
        raise ValueError(f"unknown report kind {kind!r}; one of {', '.join(KINDS)}")
    label, default = KINDS[kind]
    sections = [s for s in (sections or []) if s in default] or default
    ref = str(ref_id or "").lstrip("#")
    who = name(company)
    d = Doc(f"{label}: {who}" if kind in ("plan", "agenda", "memo") else f"{label}: {'overlap #' + ref if ref.isdigit() else ref}")
    if kind == "plan":
        sec_plan(conn, company, ref or None, sections, d)
    elif kind == "finding":
        sec_finding(conn, company, ref, sections, d)
    elif kind == "agenda":
        sec_agenda(conn, company, ref, sections, options, d)
    elif kind == "memo":
        sec_memo(conn, company, ref, sections, options, d)
    else:
        if not ref:
            raise ValueError("this report needs an overlap id like #18" + (" or a site id" if kind == "hazard_exposure" else ""))
        opp = int(ref) if ref.isdigit() else None
        if kind == "feasibility":
            sec_feasibility(conn, company, opp, sections, d)
        elif kind == "cost_analysis":
            sec_cost(conn, company, opp, sections, d)
        elif kind == "hazard_exposure":
            sec_hazards(conn, company, ref, sections, d)
        else:
            if "brief" in sections:
                sec_brief(conn, company, opp, d)
            if "feasibility" in sections:
                sec_feasibility(conn, company, opp, KINDS["feasibility"][1], d)
            if "cost_analysis" in sections:
                sec_cost(conn, company, opp, KINDS["cost_analysis"][1], d)
            if "hazard_exposure" in sections:
                sec_hazards(conn, company, ref, KINDS["hazard_exposure"][1], d)
    summary = " ".join(s.strip() for s in d.summary if s and s.strip())
    if kind == "pack" and d.summary:
        tail = d.summary[1].split("Scheduling", 1) if len(d.summary) > 1 else []  # the cost summary repeats the pair line; keep only its savings sentence
        summary = d.summary[0].strip() + (" Scheduling" + tail[1].rstrip() if len(tail) == 2 else "")
    return d, sections, summary, ref


def render(conn, company, kind, ref_id=None, sub=None):
    """The page for a kind and id without storing it (share links)."""
    d, _, summary, _ = compose(conn, company, kind, ref_id)
    return page(d.title, sub or d.subtitle or f"{name(company)} · crewly", "".join(d.parts), summary, d.figures[:5], d.sources, d.head)


def build(conn, company, kind, ref_id=None, sections=None, options=None):
    """Render one report and store it; returns the row plus the summary and key figures."""
    d, sections, summary, ref = compose(conn, company, kind, ref_id, sections, options)
    doc = page(d.title, d.subtitle or f"{name(company)} · crewly", "".join(d.parts), summary, d.figures[:5], d.sources, d.head)
    conn.execute(TABLE_SQL)
    row = conn.execute("INSERT INTO report (company_id, kind, ref_id, title, sections, html) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at",
                       (company, kind, ref or None, d.title, sections, doc)).fetchone()
    return {"id": row["id"], "kind": kind, "ref_id": ref or None, "title": d.title, "sections": sections, "all_sections": KINDS[kind][1],
            "created_at": row["created_at"].isoformat(), "html": doc, "summary": summary, "figures": d.figures[:5]}


def get(conn, report_id, company):
    conn.execute(TABLE_SQL)
    return conn.execute("SELECT id, kind, ref_id, title, sections, html, created_at FROM report WHERE id = %s AND company_id = %s", (int(report_id), company)).fetchone()


def short_partner(company, op):
    return short(op["b_org"] if op["a_org"] == company else op["a_org"])
