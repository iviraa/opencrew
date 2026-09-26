"""Forecast and season: what the hazard layers say will touch the works now, this season and in the cheapest months."""
from app.feasibility.common import factor

HEAVY, LIGHT = 0.25, 0.08  # share of a period's days affected: above HEAVY is a real drag, below LIGHT barely matters


def assess(ctx):
    hz = ctx.get("hazards") or {}
    now7, season, coord = hz.get("now7"), hz.get("season"), ctx.get("coordination") or {}
    sources = ["NWS alerts, SPC/WPC/NHC outlooks, NIFC fires, USGS quakes", "NOAA Storm Events ten-year county history"]
    if not now7 and not season:
        return factor("forecast", "Forecast and season", None, ["hazard layers not available for this pair"], [], sources)
    evidence, conditions, score = [], [], 0.8
    if now7:
        n = now7["affected_days"]["forecast"]
        worst = now7["hazards"][0]["label"] if now7["hazards"] else None
        evidence.append(f"next 7 days: {n} affected day{'s' if n != 1 else ''}" + (f", mostly {worst.lower()}" if worst and n else ""))
        active = [x["label"] for h in now7["hazards"] for x in h.get("live", [])][:2]
        if active:
            evidence.append("active now: " + "; ".join(active))
    if season:
        days, total = season["affected_days"], max(season.get("days") or 1, 1)
        ratio = float(days["high"]) / total
        worst = season["hazards"][0] if season["hazards"] else None
        evidence.append(f"next season ({season['start']} to {season['end']}): {days['low']} to {days['high']} affected days of {total}"
                        + (f", led by {worst['label'].lower()}" if worst else ""))
        if ratio >= HEAVY:
            score -= 0.35
            conditions.append("plan the shared work outside the exposed months")
        elif ratio >= LIGHT:
            score -= 0.15
        leans = [l for h in season["hazards"] for l in h.get("leans", [])][:2]
        if leans:
            evidence.append("outlook leans: " + "; ".join(leans))
    if coord.get("best_months"):
        best = coord["best_months"]
        evidence.append("least exposed months for the pair: " + ", ".join(m["label"] for m in best))
        sv = best[0].get("saves_vs_period") or {}
        if sv.get("high"):
            conditions.append(f"working in {best[0]['label']} instead saves up to ${sv['high'] / 1e3:.0f}k of weather cost per 30 days")
    return factor("forecast", "Forecast and season", score, evidence, conditions, sources)
