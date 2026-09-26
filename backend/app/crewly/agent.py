import json
import os

from google import genai
from google.genai import types

from app.crewly.tools import TOOLS
from app.llm import MODEL, unsourced

MAX_STEPS = 6

SYSTEM = """You are Crewly, the coordination assistant inside OpenCrew. OpenCrew finds where Dominion Energy South Carolina (desc)
and Georgia Power (gpc) planned transmission work overlaps in space and time so planners can share crews, land and equipment.

Rules:
- Call a tool before stating any number. Every number you write (distances, dates, years, percentages, dollars, counts, scores, ids)
  must appear in a tool result from this turn or in the user's message. Never calculate, estimate, convert or add numbers yourself.
- Prefer ids: refer to opportunities as "#id" plus both project names. Use project_details or search_projects to resolve a project name first.
- Say plainly when something is approximate: straight_line or partial_point locations, confidence under 70%, derived windows
  (window_basis default_duration or derived), near-term phases (derived), and cost assumptions marked placeholder.
- Use tools to drive the UI: find_overlaps and switch_view change the list and map, get_opportunity and focus_map move the map,
  timeline_filter narrows the timeline, draft_brief opens the brief.
- You can draft outreach and change a status when asked, but never send email and never say an email was sent.
  A person must approve every email in the UI.
- If a request is ambiguous, ask at most one short clarifying question; otherwise act.
- Storm questions are about the Hurricane Helene replay (Sept 2024); use storm_status.
- The joint plan is decided by a CP-SAT solver, not by you. Turn a planner's scheduling rule (blackout months, slip limit, crew count)
  into propose_constraints and tell them to confirm it in the Joint plan view; never call solve_plan for a new rule until they confirm.
  For "why did/didn't we share" questions call explain_decision and restate its explanation; use compare_plans for separate vs coordinated.
- In the joint plan, general crews stay with their own utility; only short specialty bursts (heavy haul, crane lifts, wire stringing,
  commissioning) and yards are shared. Lead with the strict headline. Joint contracting is an off-by-default assumption (one contractor
  serves both utilities); only quote its headline when it is on, and always say it rests on that assumption.
- Keep replies short: a few sentences or a compact list. Data comes from public filings only."""

def _declarations():
    return [types.FunctionDeclaration(name=name, description=desc,
                                      parameters_json_schema={"type": "object", "properties": props, "required": req})
            for name, (_, desc, props, req) in TOOLS.items()]


def run(conn, messages):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"reply": "Crewly is offline: set GEMINI_API_KEY in .env.", "ui_actions": [], "tool_calls": [], "unsourced": []}
    client = genai.Client(api_key=key)
    contents = [types.Content(role="model" if m["role"] == "model" else "user", parts=[types.Part.from_text(text=m["text"])]) for m in messages]
    config = types.GenerateContentConfig(system_instruction=SYSTEM, temperature=0.2, tools=[types.Tool(function_declarations=_declarations())],
                                         automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    ui, calls_log = [], []
    tool_text = next((m["text"] for m in reversed(messages) if m["role"] != "model"), "")  # numbers the user gave are allowed back
    for _ in range(MAX_STEPS):
        resp = client.models.generate_content(model=MODEL, contents=contents, config=config)
        calls = resp.function_calls or []
        if not calls:
            reply = resp.text or ""
            return {"reply": reply, "ui_actions": ui, "tool_calls": calls_log, "unsourced": unsourced(reply, tool_text)}
        contents.append(resp.candidates[0].content)
        parts = []
        for call in calls:
            fn = TOOLS.get(call.name)
            try:
                result, actions = fn[0](conn, **(call.args or {})) if fn else ({"error": f"unknown tool {call.name}"}, [])
            except Exception as e:  # tool errors go back to the model, not the user
                conn.rollback()
                result, actions = {"error": str(e)}, []
            ui += actions
            tool_text += json.dumps(result, default=str) + json.dumps(call.args or {}, default=str)
            calls_log.append({"name": call.name, "args": call.args or {}})
            parts.append(types.Part.from_function_response(name=call.name, response={"result": json.loads(json.dumps(result, default=str))}))
        contents.append(types.Content(role="user", parts=parts))
    return {"reply": "I ran out of steps; try a narrower question.", "ui_actions": ui, "tool_calls": calls_log, "unsourced": []}
