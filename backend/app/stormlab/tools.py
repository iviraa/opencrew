"""Crewly abilities: run a what-if storm, replay the last ten years, rank what moves a number. Each returns a finding card."""
from app.stormlab import EXPERIMENTS
from app.stormlab.finding import usd


def _bind(ctx, kind):
    def call(conn, **kw):
        f = EXPERIMENTS[kind](conn, ctx["company"], kw)
        m = f["scenario"]["metrics"]
        summary = {"finding_id": f["id"], "title": f["title"],
                   "headline": {k: (usd(v["value"]) if v["unit"] == "usd" else v["value"]) for k, v in m.items()},
                   "evidence": f["evidence"][:5], "notes": f["notes"][:1]}
        return summary, [{"type": "finding", "finding": f}]
    return call


PROMPT = """
- For "what if a hurricane/storm hits <place> on <date>", "a category N at <place>", or "replay Helene" call storm_scenario; give the headline
  (our sites exposed, affected days, extra cost, neighbors with capacity nearby) and let the finding card carry the rest. Say "capacity
  available nearby", never that anyone is sent anywhere.
- For "how would this plan/overlap have done over the last ten years", "worst year", "best and worst case from history" call history_replay.
- For "what moves the savings/weather cost most", "which assumption matters", "how sensitive is #N" call sensitivity.
- These are experiments: nothing real changes. Lead with the biggest delta, in one sentence, then the numbers that back it."""


def stormlab_tools(ctx):
    return {
        "storm_scenario": (_bind(ctx, "storm"), "What-if storm over our active sites and our neighbors': a place (county or city), a date and a "
                           "category (or max wind mph); or historical='helene' for the real Helene track. Returns exposed sites, affected days, "
                           "extra cost, neighbor capacity nearby and coordination savings as a finding card.", {
            "place": {"type": "string", "description": "county or city, e.g. Charleston"}, "state": {"type": "string", "description": "two letters"},
            "lon": {"type": "number"}, "lat": {"type": "number"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
            "category": {"type": "integer", "description": "1 to 5; omit for a tropical storm when max_wind_mph is given"},
            "max_wind_mph": {"type": "number"}, "historical": {"type": "string", "enum": ["helene"]},
            "heading_deg": {"type": "number", "description": "track heading, default 20 (north-north-east)"}}, []),
        "history_replay": (_bind(ctx, "replay"), "Run overlaps, sites or the latest plan through each of the last ten real years of weather: "
                           "distribution of affected days and cost, best and worst year, with a chart.", {
            "opportunity_ids": {"type": "array", "items": {"type": "integer"}}, "job_ids": {"type": "array", "items": {"type": "string"}},
            "plan_id": {"type": "integer"}, "years": {"type": "array", "items": {"type": "integer"}},
            "hazards": {"type": "array", "items": {"type": "string"}}}, []),
        "sensitivity": (_bind(ctx, "sensitivity"), "Which assumption moves an overlap's coordination savings or weather cost most: each knob is "
                        "moved 25% below and above on its own and ranked by swing (a tornado chart).", {
            "opportunity_id": {"type": "integer"}, "metric": {"type": "string", "enum": ["savings", "weather_cost"]},
            "knobs": {"type": "array", "items": {"type": "string"}, "description": "assumption keys, drive_min, shift_months"},
            "month": {"type": "integer", "description": "1-12, for weather cost"}}, ["opportunity_id"]),
    }
