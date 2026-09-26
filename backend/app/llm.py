import os
import re

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers(text):
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}


def unsourced(reply, tool_text):
    allowed = numbers(tool_text)
    return sorted(n for n in numbers(reply) if n not in allowed and n.lstrip("0") not in allowed)
