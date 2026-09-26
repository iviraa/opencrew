import os
import re

import httpx

import app.db  # noqa: F401  loads .env so keys work from any entry point

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACKS = [MODEL, "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3-flash-preview", "gemini-flash-latest",
             "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash"]  # busy or retired models fall through
SPENT = {}  # model -> day its daily quota ran out, so we skip it until tomorrow

LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")
NUMBER = re.compile(r"(\$)?(\d[\d,]*(?:\.\d+)?)(?:\s?([kKmM])(?![a-zA-Z]))?(\s?%)?")
SCALE = {"k": 1e3, "m": 1e6}


def parse(text):
    out = []
    for m in NUMBER.finditer(LIST_MARKER.sub(" ", text)):
        raw = m.group(2).replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        scale = SCALE[m.group(3).lower()] if m.group(1) and m.group(3) else 1.0  # $200k, $1.2M
        out.append((m.group(0).strip(), float(raw), decimals, scale, bool(m.group(4))))
    return out


def numbers(text):
    return {v * scale for _, v, _, scale, _ in parse(text)}


def sourced(value, decimals, scale, percent, allowed):
    tol = 0.5 * 10 ** -decimals + 1e-9  # a correctly rounded copy of a sourced number is fine
    return any(abs(a / scale - value) <= tol or (percent and abs(a * 100 - value) <= tol) for a in allowed)


def unsourced(reply, source_text):
    allowed = {v * scale for _, v, _, scale, _ in parse(source_text)}
    return sorted({raw for raw, v, dec, scale, pct in parse(reply) if not sourced(v, dec, scale, pct, allowed)})


def provider():
    if os.environ.get("LLM_PROVIDER"):
        return os.environ["LLM_PROVIDER"]
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini"
    return "local" if os.environ.get("LOCAL_LLM_URL") else None  # any OpenAI-compatible server: llama.cpp :8080/v1, ollama :11434/v1


def local_chat(messages, tools=None, schema=None, max_tokens=3000):
    body = {"model": os.environ.get("LOCAL_LLM_MODEL") or "local", "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}  # ollama needs the tag
    if tools:
        body |= {"tools": tools, "tool_choice": "auto"}
    if schema:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
    r = httpx.post(f"{os.environ['LOCAL_LLM_URL'].rstrip('/')}/chat/completions", json=body, timeout=900)  # local reasoning models are slow
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def gemini(call):
    """Run call(client, model) with retries on busy (429/503) and missing (404) models."""
    import time
    from google import genai
    from google.genai import errors
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # keep a reference: the sdk closes its http client when collected
    last = None
    today = time.strftime("%Y-%m-%d", time.gmtime())
    for model in [m for m in dict.fromkeys(FALLBACKS) if SPENT.get(m) != today]:
        for attempt in range(2):
            try:
                return call(client, model)
            except (errors.ServerError, errors.ClientError) as e:
                last = e
                if getattr(e, "code", None) not in (429, 500, 503, 404):
                    raise
                if e.code == 404:
                    break  # this model is gone for this key, try the next
                if e.code == 429 and "PerDay" in str(e):
                    SPENT[model] = today  # out for the day, no point retrying
                    break
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Gemini is busy right now: {last}")


def generate(prompt):
    if provider() == "local":
        return (local_chat([{"role": "user", "content": prompt}]).get("content") or "").strip()
    return gemini(lambda client, model: client.models.generate_content(model=model, contents=prompt).text.strip())


def generate_json(prompt, schema):
    """Raw JSON text constrained to the schema."""
    if provider() == "local":
        return local_chat([{"role": "user", "content": prompt}], schema=schema).get("content") or "{}"
    from google.genai import types
    config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema, temperature=0)
    return gemini(lambda client, model: client.models.generate_content(model=model, contents=prompt, config=config).text)
