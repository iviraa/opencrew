"""Findings: what an experiment learned, in one shape every card and notebook understands."""
import json
from datetime import datetime, timezone

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS finding (
  id SERIAL PRIMARY KEY, company_id TEXT, title TEXT, kind TEXT, params JSONB, result JSONB,
  starred BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT now()
)"""
METRICS = {  # standard names shared with the scenario fork, with their units and labels
    "affected_days_low": ("days", "Weather-affected days, low"), "affected_days_high": ("days", "Weather-affected days, high"),
    "weather_cost_low": ("usd", "Expected extra cost, low"), "weather_cost_high": ("usd", "Expected extra cost, high"),
    "exposed_sites": ("sites", "Our sites exposed"), "exposed_projects": ("projects", "Projects exposed, ours and neighbors'"),
    "neighbors_with_capacity": ("sites", "Neighbor sites nearby outside the storm"),
    "savings_low": ("usd", "Coordination savings, low"), "savings_high": ("usd", "Coordination savings, high"),
    "worst_year": ("year", "Worst year"), "best_year": ("year", "Best year"),
}


def metric(name, value, low=None, high=None, unit=None, label=None):
    u, lbl = METRICS.get(name, (unit or "", label or name))
    out = {"value": value, "unit": unit or u, "label": label or lbl}
    if low is not None:
        out["low"] = low
    if high is not None:
        out["high"] = high
    return out


def metrics(**values):
    return {k: metric(k, v) for k, v in values.items()}


def deltas(base, scenario):
    """One delta row per metric present on both sides."""
    out = []
    for k, s in scenario.items():
        b = base.get(k)
        if b is None or not isinstance(s.get("value"), (int, float)) or not isinstance(b.get("value"), (int, float)):
            continue
        d = s["value"] - b["value"]
        out.append({"metric": k, "label": s["label"], "base": b["value"], "scenario": s["value"], "delta": round(d, 1),
                    "pct": round(d / b["value"] * 100) if b["value"] else None, "unit": s["unit"]})
    return out


def knob(name, kind, value, label, **extra):
    return {"name": name, "type": kind, "value": value, "label": label, **extra}


def make(kind, title, question, params, base, scenario, notes=(), evidence=(), knobs=(), sources=(), **extra):
    return {"id": None, "title": title, "question": question, "kind": kind, "params": params, "base": {"metrics": base}, "scenario": {"metrics": scenario},
            "deltas": deltas(base, scenario), "notes": list(notes), "evidence": list(evidence), "knobs": list(knobs), "sources": list(sources),
            "created_at": datetime.now(timezone.utc).isoformat(), **extra}


def save(conn, company, f):
    """Store the finding and hand it back with its id."""
    conn.execute(TABLE_SQL)
    row = conn.execute("INSERT INTO finding (company_id, title, kind, params, result) VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at",
                       (company, f["title"], f["kind"], json.dumps(f["params"], default=str), json.dumps(f, default=str))).fetchone()
    f["id"], f["created_at"] = row["id"], row["created_at"].isoformat()
    return f


def usd(n):
    n = float(n)
    return f"${n / 1e6:.1f}M" if abs(n) >= 1e6 else f"${round(n / 1e3)}k" if abs(n) >= 1e3 else f"${round(n)}"
