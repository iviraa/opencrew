"""News: what recent reporting about either utility or project area means for this pair (the pipeline is optional)."""
from app.feasibility.common import factor

NEGATIVE = {"delay": 0.2, "cancellation": 0.35, "opposition": 0.2, "regulatory": 0.15, "funding": 0.15, "security": 0.1}
TIMING = {"damage": 0.1, "outage": 0.1, "storm": 0.1}
POSITIVE = {"approval": 0.05, "progress": 0.05, "funding_secured": 0.05}


def fetch(conn, opportunity_id, days=90):
    """Stories for this overlap from app.news.feed when that package exists; None when it does not."""
    try:
        from app.news import feed
    except ImportError:
        return None
    try:
        return list(feed.for_overlap(conn, opportunity_id, days=days))
    except Exception:
        return None


def assess(ctx):
    items = ctx.get("news")
    sources = ["utility-first news pipeline (app.news)"]
    if items is None:
        return factor("news", "News and events", None, ["news pipeline not available"], [], sources)
    if not items:
        return factor("news", "News and events", 0.6, ["no relevant news in the last 90 days"], [], sources)
    score, evidence, conditions = 0.75, [], []
    for it in sorted(items, key=lambda x: -(x.get("confidence") or 0))[:5]:
        impact = (it.get("impact") or "").lower()
        line = f"{impact or 'news'}: {it.get('title', '')[:90]} ({it.get('source', '')}, {str(it.get('published', ''))[:10]})"
        evidence.append(line)
        if impact in NEGATIVE:
            score -= NEGATIVE[impact] * (it.get("confidence") or 0.7)
            conditions.append(f"check how the {impact} reported for '{it.get('title', '')[:50]}' affects the schedule")
        elif impact in TIMING:
            score -= TIMING[impact] * (it.get("confidence") or 0.7)
            conditions.append("recent damage or outages pull crews to restoration first")
        elif impact in POSITIVE:
            score += POSITIVE[impact]
    return factor("news", "News and events", score, evidence, conditions, sources, count=len(items))
