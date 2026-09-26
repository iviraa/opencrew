"""Shared shape of a factor result and the small helpers every factor uses."""
from datetime import date, datetime

VERDICTS = ("strong", "possible", "unlikely", "unknown")
STRONG, POSSIBLE = 0.7, 0.4  # score cut-offs


def verdict_for(score):
    if score is None:
        return "unknown"
    return "strong" if score >= STRONG else "possible" if score >= POSSIBLE else "unlikely"


def factor(name, label, score, evidence, conditions=(), sources=(), **extra):
    """A factor result: the verdict follows the score unless a caller sets one; evidence lines carry the numbers."""
    return {"factor": name, "label": label, "verdict": verdict_for(score), "score": None if score is None else round(min(max(score, 0.0), 1.0), 2),
            "evidence": [e for e in evidence if e], "conditions": [c for c in conditions if c], "sources": list(dict.fromkeys(s for s in sources if s)),
            **extra}


def money(n):
    n = float(n or 0)
    return f"${n / 1e6:.1f}M" if n >= 1e6 else f"${n / 1e3:.0f}k" if n >= 1e3 else f"${n:,.0f}"


def span(lo, hi):
    return money(lo) if round(float(lo or 0)) == round(float(hi or 0)) else f"{money(lo)} to {money(hi)}"


def day(d):
    return d.date() if isinstance(d, datetime) else d


def months_between(a, b):
    a, b = day(a), day(b)
    return (b.year - a.year) * 12 + b.month - a.month + (b.day - a.day) / 30.0


def ym(d):
    return f"{day(d):%b %Y}" if d else "?"


def today_or(ctx):
    return ctx.get("today") or date.today()
