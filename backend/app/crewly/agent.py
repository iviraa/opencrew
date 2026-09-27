import json

from google.genai import types

from app.crewly.tools import TOOLS
from app.llm import gemini, local_chat, provider, unsourced

MAX_STEPS = 10

SYSTEM = """You are Crewly, the coordination assistant inside OpenCrew. OpenCrew finds where Dominion Energy South Carolina (desc)
and Georgia Power (gpc) planned transmission work overlaps in space and time so planners can share crews, land and equipment.

Rules:
- Call a tool before stating any number. Every number you write (distances, dates, years, percentages, dollars, counts, scores, ids)
  must appear in a tool result from this turn or in the user's message. Never calculate, estimate, convert or add numbers yourself.
- Prefer ids: refer to opportunities as "#id" plus both project names. Use project_details or search_projects to resolve a project name first.
- Say plainly when something is approximate: straight_line or partial_point locations, confidence under 70%, derived windows
  (window_basis default_duration or derived), near-term phases (derived), and cost assumptions marked estimate (each has a source and note).
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

def _declarations(tools=TOOLS):
    return [types.FunctionDeclaration(name=name, description=desc,
                                      parameters_json_schema={"type": "object", "properties": props, "required": req})
            for name, (_, desc, props, req) in tools.items()]


def execute(conn, name, args, tools=TOOLS):
    fn = tools.get(name)
    try:
        return fn[0](conn, **args) if fn else ({"error": f"unknown tool {name}"}, [])
    except Exception as e:  # tool errors go back to the model, not the user
        conn.rollback()
        return {"error": str(e)}, []


def run(conn, messages, system=SYSTEM, tools=TOOLS):
    which = provider()
    if not which:
        return {"reply": "Crewly is offline: set GEMINI_API_KEY or LOCAL_LLM_URL in .env.", "ui_actions": [], "tool_calls": [], "unsourced": []}
    try:
        return run_local(conn, messages, system, tools) if which == "local" else run_gemini(conn, messages, system, tools)
    except Exception as e:  # model outages become a reply, not a 500
        conn.rollback()
        return {"reply": offline_reply(e), "ui_actions": [], "tool_calls": [], "unsourced": [], "offline": True}


def offline_reply(e):
    text = str(e)
    if "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():  # free tier daily limits
        return "I've used up my thinking time for today (the Gemini quota ran out), so I can't answer right now. The map, overlaps and requests all still work."
    return "I couldn't reach my brain just now. Please try again in a minute."


def run_local(conn, messages, system=SYSTEM, tools=TOOLS):
    decls = [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": r}}}
             for n, (_, d, p, r) in tools.items()]
    msgs = [{"role": "system", "content": system}] + [{"role": "assistant" if m["role"] == "model" else "user", "content": m["text"]} for m in messages]
    ui, calls_log = [], []
    tool_text = next((m["text"] for m in reversed(messages) if m["role"] != "model"), "")  # numbers the user gave are allowed back
    for _ in range(MAX_STEPS):
        msg = local_chat(msgs, tools=decls)
        calls = msg.get("tool_calls") or []
        if not calls:
            reply = (msg.get("content") or "").strip()
            return {"reply": reply, "ui_actions": ui, "tool_calls": calls_log, "unsourced": unsourced(reply, tool_text)}
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result, actions = execute(conn, name, args, tools)
            ui += actions
            tool_text += json.dumps(result, default=str) + json.dumps(args, default=str)
            calls_log.append({"name": name, "args": args})
            msgs.append({"role": "tool", "tool_call_id": call.get("id", name), "content": json.dumps(result, default=str)})
    msgs.append({"role": "user", "content": "Stop calling tools. Answer now from what you have, in two sentences, and say what you could not finish."})
    reply = (local_chat(msgs).get("content") or "").strip() or "I gathered part of this; ask for one piece at a time and I will finish it."
    return {"reply": reply, "ui_actions": ui, "tool_calls": calls_log, "unsourced": unsourced(reply, tool_text)}


def run_gemini(conn, messages, system=SYSTEM, tools=TOOLS):
    contents = [types.Content(role="model" if m["role"] == "model" else "user", parts=[types.Part.from_text(text=m["text"])]) for m in messages]
    config = types.GenerateContentConfig(system_instruction=system, temperature=0.2, tools=[types.Tool(function_declarations=_declarations(tools))],
                                         automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    ui, calls_log = [], []
    tool_text = next((m["text"] for m in reversed(messages) if m["role"] != "model"), "")  # numbers the user gave are allowed back
    for _ in range(MAX_STEPS):
        resp = gemini(lambda client, model: client.models.generate_content(model=model, contents=contents, config=config))
        calls = resp.function_calls or []
        if not calls:
            reply = resp.text or ""
            return {"reply": reply, "ui_actions": ui, "tool_calls": calls_log, "unsourced": unsourced(reply, tool_text)}
        contents.append(resp.candidates[0].content)
        parts = []
        for call in calls:
            result, actions = execute(conn, call.name, call.args or {}, tools)
            ui += actions
            tool_text += json.dumps(result, default=str) + json.dumps(call.args or {}, default=str)
            calls_log.append({"name": call.name, "args": call.args or {}})
            parts.append(types.Part.from_function_response(name=call.name, response={"result": json.loads(json.dumps(result, default=str))}))
        contents.append(types.Content(role="user", parts=parts))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text="Stop calling tools. Answer now from what you have, in two sentences, and say what you could not finish.")]))
    closing = types.GenerateContentConfig(system_instruction=system, temperature=0.2)  # no tools: the model has to write
    resp = gemini(lambda client, model: client.models.generate_content(model=model, contents=contents, config=closing))
    reply = (resp.text or "").strip() or "I gathered part of this; ask for one piece at a time and I will finish it."
    return {"reply": reply, "ui_actions": ui, "tool_calls": calls_log, "unsourced": unsourced(reply, tool_text)}
