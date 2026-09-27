"""Crewly abilities that hand something over: a chart, a data table, a printable report, or exactly the overlaps it means."""
import re

from app.crewly import charts, reports

CITED = re.compile(r"#(\d{1,7})\b")
DOCUMENTS = {"report", "draft"}  # cards that are the answer on their own


def settle(conn, company, out):
    """After the answer: the cards match the words. A document is not shadowed by the plan it read, and overlap cards follow the ids named."""
    from app.crewly.app_tools import mine_sql
    ui, reply = list(out.get("ui_actions") or []), out.get("reply") or ""
    if any(a.get("type") in DOCUMENTS for a in ui):
        ui = [a for a in ui if a.get("type") != "plan"]  # the plan was only read to write the document
    shows = [a for a in ui if a.get("type") == "show_overlaps"]
    cited = list(dict.fromkeys(int(m) for m in CITED.findall(reply)))
    if shows and cited:
        listed = {i for a in ui if a.get("type") in ("show_overlaps", "open_overlap") for i in (a.get("ids") or [a.get("id")]) if i}  # ids a tool returned this turn
        keep = [i for i in cited if i in listed][:25]  # "#2" inside a project name is not an overlap the answer named
        if not keep:
            ours = {r["id"] for r in conn.execute(mine_sql(company) + " AND op.id = ANY(%s)", (cited,)).fetchall()}
            keep = [i for i in cited if i in ours][:25]
        if keep and set(keep) != set(shows[-1]["ids"]):
            shows[-1]["ids"] = keep  # the cards follow the answer, not the model's first guess
        ui = [a for a in ui if a.get("type") != "show_overlaps" or a is shows[-1]]
    out["ui_actions"] = ui
    return out


def _bind(ctx, fn):
    return lambda conn, **kw: fn(ctx, conn, **kw)


def show_overlaps(ctx, conn, ids, title=None):
    """Exactly these overlaps as cards on the map and in the chat, in this order."""
    from app.crewly.app_tools import mine_sql
    want = [int(str(i).lstrip("#")) for i in (ids or []) if str(i).lstrip("#").isdigit()][:25]
    ours = {r["id"] for r in conn.execute(mine_sql(ctx["company"]) + " AND op.id = ANY(%s)", (want,)).fetchall()} if want else set()
    kept = [i for i in want if i in ours]
    title = re.sub(r"<[^>]*>", "", str(title or "")).strip()[:80]  # a card title is plain text
    return {"shown": kept, "not_ours": [i for i in want if i not in ours]}, [{"type": "show_overlaps", "ids": kept, **({"title": title} if title else {})}]


def _brief(chart):
    return {"title": chart["title"], "kind": chart["kind"], "unit": chart["unit"], "x": chart["x"][:24],
            "series": [{"name": s["name"], "values": s["values"][:24]} for s in chart["series"]], "source": chart["source"]}


def make_chart(ctx, conn, dataset, options=None, compare=None):
    """One chart, or two side by side when compare names the second (same dataset by default, other options)."""
    chart, _ = charts.make(conn, ctx["company"], dataset, options or {})
    if not compare:
        return _brief(chart), [{"type": "chart", "chart": chart}]
    other, _ = charts.make(conn, ctx["company"], compare.get("dataset") or dataset, compare.get("options") or {})
    return {"left": _brief(chart), "right": _brief(other), "shown": "side by side"}, [{"type": "chart", "chart": chart, "compare": other}]


def get_data(ctx, conn, dataset, filters=None):
    t = charts.table(conn, ctx["company"], dataset, filters or {}, ctx)
    return {**t, "rows": t["rows"][:15], "note": f"{t['count']} rows in the table card" if t["count"] > 15 else None}, [{"type": "table", "table": t}]


def make_report(ctx, conn, kind, id=None, sections=None):
    r = reports.build(conn, ctx["company"], kind, id, sections)
    card = {k: r[k] for k in ("id", "kind", "ref_id", "title", "sections", "all_sections", "created_at", "summary", "figures")}
    return {**card, "next_step": "the report card in the chat opens it; the page has a Print / Save as PDF button"}, [{"type": "report", "report": card}]


def generate_tools(ctx):
    datasets = ", ".join(f"{k} ({v[1]})" for k, v in charts.DATASETS.items())
    tables = ", ".join([*charts.TABLES, "requests"])
    return {
        "show_overlaps": (_bind(ctx, show_overlaps), "Show exactly these overlaps as cards and on the map, in this order. Call it last, once you "
                          "have decided which overlaps your answer names (e.g. 'top 2', 'best by criteria'), so the cards match what you said.", {
            "ids": {"type": "array", "items": {"type": "integer"}, "description": "overlap ids, in the order to show"},
            "title": {"type": "string", "description": "short card title, e.g. 'Top 2 by savings'"}}, ["ids"]),
        "make_chart": (_bind(ctx, make_chart), "Build a chart card in the chat from one dataset: " + datasets + ". options: kind (bar, line, stacked), "
                       "years [from, to], partner (utility name), id (site or overlap), hazards, top, days, horizon. The card has PNG and CSV downloads.", {
            "dataset": {"type": "string", "enum": list(charts.DATASETS)},
            "options": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": list(charts.KINDS)}, "years": {"type": "array", "items": {"type": "integer"}},
                "partner": {"type": "string"}, "id": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}, "description": "several overlaps or sites to compare in one chart"},
                "hazards": {"type": "array", "items": {"type": "string"}},
                "top": {"type": "integer"}, "days": {"type": "integer"}, "horizon": {"type": "string"}}},
            "compare": {"type": "object", "description": "a second chart shown side by side: {dataset (defaults to the same), options}; use it for "
                        "'side by side', 'compare this with', or two views of one question", "properties": {
                "dataset": {"type": "string", "enum": list(charts.DATASETS)}, "options": {"type": "object"}}}}, ["dataset"]),
        "get_data": (_bind(ctx, get_data), "Hand over data as a table card with a CSV download. Tables: " + tables + "; or any chart dataset's rows. "
                     "filters: years [from, to], partner, tier, verdict, state, status, id (site or overlap), period, month, days, impact, direction, top.", {
            "dataset": {"type": "string", "enum": [*charts.TABLES, "requests", *charts.DATASETS]},
            "filters": {"type": "object", "properties": {
                "years": {"type": "array", "items": {"type": "integer"}}, "partner": {"type": "string"}, "tier": {"type": "string"},
                "verdict": {"type": "string"}, "state": {"type": "string"}, "status": {"type": "string"}, "id": {"type": "string"},
                "period": {"type": "string"}, "month": {"type": "integer"}, "days": {"type": "integer"}, "impact": {"type": "string"},
                "direction": {"type": "string"}, "top": {"type": "integer"}}}}, ["dataset"]),
        "make_report": (_bind(ctx, make_report), "Write a printable report (opens as a page with Print / Save as PDF): feasibility, cost_analysis or "
                        "hazard_exposure for an overlap (#id) or site, plan for the plan the user last saw (no id needed; id = horizon picks another), "
                        "pack (brief + feasibility + cost + hazards for one overlap), or comparison (two to six overlaps side by side with a ranking; id = the ids "
                        "joined by commas, e.g. '13,14,15'). Optional sections to include. Never build a plan first.", {
            "kind": {"type": "string", "enum": list(reports.KINDS)}, "id": {"type": "string", "description": "overlap #id, site id, a plan horizon, or comma-joined overlap ids for a comparison"},
            "sections": {"type": "array", "items": {"type": "string"}}}, ["kind"]),
    }


PROMPT = """
- When the user asks for a number of things ("top 2", "the 5 biggest") or which overlaps are best by some criteria, answer from my_overlaps
  (limit=N) or get_data, then call show_overlaps last with exactly the ids you named, in that order, so the cards match your words. Never let
  a card show more than you named, and never build a plan to answer a "which/best/top" question.
- For "chart", "graph", "plot", "trend" or "visualize" call make_chart once with the dataset that fits and options from the user's words (years,
  top N, partner, kind; ids to put several overlaps in one chart, never one chart per overlap; compare for two charts side by side,
  e.g. savings by partner next to overlaps by month, or one overlap's months next to another's); for "give me the data", "export", "list every", "as a table" call get_data; for "report", "printout", "document",
  "PDF" or "write up" call make_report on its own (kind comparison when the user names or means several overlaps): it reads the latest plan, finding or overlap itself, so do not build a plan or list
  overlaps first. Then describe the result in one sentence; the card carries the numbers, so do not restate them."""
