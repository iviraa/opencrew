import json

from app.db import ROOT
from app.llm import generate_json, provider

CACHE = ROOT / "data/layers/llm_geo_cache.json"
SCHEMA = {"type": "object", "properties": {"choice": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["choice"]}
PROMPT = """A utility filing describes a transmission project. Pick which candidate substation or plant (from OpenStreetMap) is the site
this project names. Only pick when a candidate's name clearly refers to the same station; if none does, answer -1. Never guess.

Project: {name}
Description: {desc}

Candidates:
{options}

Answer with the candidate number or -1."""


def _cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def choose(job, options):
    """Gemini picks one of the given OSM candidates or none; it never supplies coordinates."""
    if not provider():
        return None
    key = f"{job['name']}|{','.join(o['osm'] for o in options)}"
    cache = _cache()
    if key not in cache:
        text = "\n".join(f"{i}. {o['name']} (operator: {o.get('operator') or 'unknown'})" for i, o in enumerate(options))
        try:
            out = json.loads(generate_json(PROMPT.format(name=job["name"], desc=(job.get("description") or "")[:600], options=text), SCHEMA))
        except Exception:
            return None  # model busy or offline: leave unplaced this run, retry next build
        cache[key] = out
        CACHE.write_text(json.dumps(cache, indent=1))
    i = cache[key].get("choice", -1)
    return options[i] if isinstance(i, int) and 0 <= i < len(options) else None
