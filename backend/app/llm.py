import os
import re

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
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
