"""Regenerate the tool catalogue in docs/crewly-abilities.md from the live registry: `uv run python -m scripts.tool_catalogue`."""
import inspect
import re
import sys

from app.crewly.app_tools import app_tools
from app.db import ROOT

DOC = ROOT / "docs/crewly-abilities.md"
START, END = "<!-- catalogue:start -->", "<!-- catalogue:end -->"
SCHEMA_TYPES = {"string", "integer", "number", "boolean", "array", "object"}  # json schema words, not cards
GROUPS = [
    ("Overlaps and projects", ["my_overlaps", "open_overlap", "show_overlaps", "search_projects", "project_details", "compare_projects", "focus_map",
                               "estimate_savings", "assess_feasibility", "explain_numbers", "explain_method"]),
    ("Requests, goals and pipeline", ["collab_requests", "propose_request", "propose_answer", "start_goal", "goal_status", "set_status", "pipeline",
                                      "overlap_history"]),
    ("Weather, hazards and news", ["outlook", "weather_alerts", "site_hazards", "site_forecast", "hazard_exposure", "hazard_cost", "incidents_near",
                                   "news_for"]),
    ("Planning", ["build_plan", "plan_status", "explain_plan_item", "plan_bulk"]),
    ("What-if, storms and math", ["run_experiment", "calculate", "compare_findings", "list_findings", "findings_bulk", "storm_scenario",
                                  "history_replay", "sensitivity"]),
    ("Charts, tables, reports and exports", ["make_chart", "get_data", "query_data", "make_report", "export", "share_link"]),
    ("Documents for people", ["draft_email", "draft_agenda", "draft_memo"]),
    ("Notes, reminders, views and memory", ["add_note", "list_notes", "set_reminder", "list_reminders", "done_reminder", "save_view", "open_view",
                                            "list_views", "weekly_brief", "company_profile", "remember", "forget", "list_memory"]),
    ("Map control", ["map_view", "filter_projects", "timeline", "route_between"]),
    ("Source refresh", ["check_for_updates", "what_changed", "promote_update"]),
]
CARDS = {  # what each card type looks like to the person
    "show_overlaps": "overlap cards + map highlight", "open_overlap": "overlap detail panel", "fly": "map moves", "select": "overlap selected",
    "filter": "list filter", "view": "view/tab switch", "reload": "list reload", "confirm": "Confirm button (nothing sent until tapped)",
    "goal": "goal chip + goal panel", "memory": "memory list", "plan": "plan card", "chart": "chart card", "table": "table card",
    "report": "report card (Print / Save as PDF page)", "finding": "what-if card", "compare": "comparison card", "draft": "draft card + Confirm",
    "note": "note card", "reminder": "reminder card", "status": "status chip", "pipeline": "pipeline card", "profile": "profile card",
    "brief": "brief card", "history": "history card", "save_view": "view saved", "views": "views card", "notebook": "notebook card",
    "refresh": "refresh card", "map_view": "map view change", "projects": "project filter on the map", "timeline": "month grid timeline",
    "forecast": "forecast card", "route": "route card + map line", "explain": "explanation card", "download": "download card",
    "share": "share-link card", "hazards": "hazard panel", "outlook": "weather panel", "storm": "storm view", "live": "live damage view",
    "assumptions": "assumptions panel", "brief_legacy": "brief"}


OVERRIDES = {  # tools whose cards come from a helper the regex cannot follow
    "hazard_exposure": ["hazards"], "hazard_cost": ["hazards"], "assess_feasibility": ["open_overlap"], "outlook": ["outlook", "fly"],
    "storm_scenario": ["finding"], "history_replay": ["finding"], "sensitivity": ["finding"], "draft_agenda": ["report"], "draft_memo": ["report"]}


def tool_cards(name, fn):
    """Card types a tool emits, read from the source of the function with its name: the bound module first, then any app module."""
    if name in OVERRIDES:
        return OVERRIDES[name]
    mods = [sys.modules[fn.__module__]] + [m for n, m in list(sys.modules.items()) if n.startswith("app.") and m is not sys.modules[fn.__module__]]
    for mod in mods:
        try:
            src = inspect.getsource(mod)
        except (OSError, TypeError):
            continue
        m = re.search(rf"^def {name}\(.*?(?=^def |\Z)", src, re.S | re.M)
        if m:
            return [t for t in dict.fromkeys(re.findall(r'\{"type": "([a-z_]+)"', m.group(0))) if t not in SCHEMA_TYPES]
    return []


def render(tools):
    seen, out = set(), []
    for title, names in GROUPS + [("Other", [n for n in tools if n not in {x for _, xs in GROUPS for x in xs}])]:
        rows = [n for n in names if n in tools]
        if not rows:
            continue
        out.append(f"\n### {title}\n\n| Tool | What it does | Inputs | Shows |\n|---|---|---|---|")
        for n in rows:
            fn, desc, props, req = tools[n]
            seen.add(n)
            inputs = ", ".join(f"**{p}**" if p in req else p for p in props) or "none"
            cards = ", ".join(CARDS.get(c, c) for c in tool_cards(n, fn)) or "text only"
            out.append(f"| `{n}` | {desc.replace('|', '/').strip()} | {inputs} | {cards} |")
    missing = set(tools) - seen
    assert not missing, missing
    return "\n".join(out) + "\n"


def main():
    tools = app_tools({"id": "doc", "company": "desc", "username": "dominion", "token": "", "memories": []})
    body = f"{START}\n\n{len(tools)} tools, generated from `app_tools()` by `backend/scripts/tool_catalogue.py`. Bold inputs are required.\n" + render(tools) + END
    text = DOC.read_text()
    assert START in text and END in text, "markers missing in the doc"
    DOC.write_text(re.sub(re.escape(START) + ".*?" + re.escape(END), lambda _: body, text, flags=re.S))
    print(len(tools), "tools written to", DOC)


if __name__ == "__main__":
    main()
