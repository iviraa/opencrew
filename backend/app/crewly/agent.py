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
- Every number you state (distances, dates, percentages, dollars, counts, scores, ids) must come from a tool result in this turn.
  Never calculate, estimate or convert numbers yourself. If you need a number, call a tool first.
- Use tools to drive the UI: find_overlaps filters the list and map, get_opportunity and focus_map move the map.
- Refer to opportunities by project names and #id. Keep replies short: a few sentences or a compact list.
- Say plainly when a location is approximate (straight_line, partial_point) or a window is derived.
- You can draft outreach but never send it. A person must approve every email in the UI.
- Storm questions are about the Hurricane Helene replay (Sept 2024); use storm_status.
- Data comes from public filings only."""

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
    ui, calls_log, tool_text = [], [], ""
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
            tool_text += json.dumps(result, default=str)
            calls_log.append({"name": call.name, "args": call.args or {}})
            parts.append(types.Part.from_function_response(name=call.name, response={"result": json.loads(json.dumps(result, default=str))}))
        contents.append(types.Content(role="user", parts=parts))
    return {"reply": "I ran out of steps; try a narrower question.", "ui_actions": ui, "tool_calls": calls_log, "unsourced": []}
