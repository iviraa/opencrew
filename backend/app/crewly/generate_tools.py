"""Crewly abilities that hand something over: a chart, a data table, a printable report, or exactly the overlaps it means."""
import re

from app.crewly import charts, reports


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


def make_chart(ctx, conn, dataset, options=None):
    chart, rows = charts.make(conn, ctx["company"], dataset, options or {})
    summary = {"title": chart["title"], "kind": chart["kind"], "unit": chart["unit"], "x": chart["x"][:24],
               "series": [{"name": s["name"], "values": s["values"][:24]} for s in chart["series"]], "source": chart["source"]}
    return summary, [{"type": "chart", "chart": chart}]


def get_data(ctx, conn, dataset, filters=None):
    t = charts.table(conn, ctx["company"], dataset, filters or {}, ctx)
    return {**t, "rows": t["rows"][:15], "note": f"{t['count']} rows in the table card" if t["count"] > 15 else None}, [{"type": "table", "table": t}]


def make_report(ctx, conn, kind, id=None, sections=None):
    r = reports.build(conn, ctx["company"], kind, id, sections)
    card = {k: r[k] for k in ("id", "kind", "ref_id", "title", "sections", "all_sections", "created_at")}
    return {**card, "next_step": "the report card in the chat opens it; the page has a Print / Save as PDF button"}, [{"type": "report", "report": card}]


def generate_tools(ctx):
    datasets = ", ".join(f"{k} ({v[1]})" for k, v in charts.DATASETS.items())
    tables = ", ".join([*charts.TABLES, "requests"])
    return {
        "show_overlaps": (_bind(ctx, show_overlaps), "Show exactly these overlaps as cards and on the map, in this order. Use it after any answer "
                          "that names specific overlaps (e.g. 'top 2'), so the cards match what you said.", {
            "ids": {"type": "array", "items": {"type": "integer"}, "description": "overlap ids, in the order to show"},
            "title": {"type": "string", "description": "short card title, e.g. 'Top 2 by savings'"}}, ["ids"]),
        "make_chart": (_bind(ctx, make_chart), "Build a chart card in the chat from one dataset: " + datasets + ". options: kind (bar, line, stacked), "
                       "years [from, to], partner (utility name), id (site or overlap), hazards, top, days, horizon. The card has PNG and CSV downloads.", {
            "dataset": {"type": "string", "enum": list(charts.DATASETS)},
            "options": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": list(charts.KINDS)}, "years": {"type": "array", "items": {"type": "integer"}},
                "partner": {"type": "string"}, "id": {"type": "string"}, "hazards": {"type": "array", "items": {"type": "string"}},
                "top": {"type": "integer"}, "days": {"type": "integer"}, "horizon": {"type": "string"}}}}, ["dataset"]),
        "get_data": (_bind(ctx, get_data), "Hand over data as a table card with a CSV download. Tables: " + tables + "; or any chart dataset's rows. "
                     "filters: years [from, to], partner, tier, verdict, state, status, id (site or overlap), period, month, days, impact, direction, top.", {
            "dataset": {"type": "string", "enum": [*charts.TABLES, "requests", *charts.DATASETS]},
            "filters": {"type": "object", "properties": {
                "years": {"type": "array", "items": {"type": "integer"}}, "partner": {"type": "string"}, "tier": {"type": "string"},
                "verdict": {"type": "string"}, "state": {"type": "string"}, "status": {"type": "string"}, "id": {"type": "string"},
                "period": {"type": "string"}, "month": {"type": "integer"}, "days": {"type": "integer"}, "impact": {"type": "string"},
                "direction": {"type": "string"}, "top": {"type": "integer"}}}}, ["dataset"]),
        "make_report": (_bind(ctx, make_report), "Write a printable report (opens as a page with Print / Save as PDF): feasibility, cost_analysis or "
                        "hazard_exposure for an overlap (#id) or site, plan for the latest plan (id = horizon), or pack (brief + feasibility + cost + "
                        "hazards for one overlap). Optional sections to include.", {
            "kind": {"type": "string", "enum": list(reports.KINDS)}, "id": {"type": "string", "description": "overlap #id, site id, or a plan horizon"},
            "sections": {"type": "array", "items": {"type": "string"}}}, ["kind"]),
    }


PROMPT = """
- When the user asks for a number of things ("top 2", "the 5 biggest"), pass limit=N to the list tool, or call show_overlaps with exactly
  those ids after you decide, so the cards match your words. Never let a card show more than you named.
- For "chart", "graph", "plot", "trend" or "visualize" call make_chart with the dataset that fits and options from the user's words (years,
  top N, partner, kind); for "give me the data", "export", "list every", "as a table" call get_data; for "report", "printout", "document",
  "PDF" or "write up" call make_report. Then describe the result in one sentence; the card carries the numbers, so do not restate them."""
