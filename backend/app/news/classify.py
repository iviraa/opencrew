"""What a story means for the work (rules first, Gemini only when rules give up) and which projects it touches."""
import json
import os
import re

from app.geo.geolocate import norm

IMPACTS = ["delay", "damage", "outage", "opposition", "regulatory", "supply_chain", "security", "funding", "construction", "other"]
AFFECTS_WORK = {"delay", "damage", "outage", "opposition", "regulatory", "supply_chain", "security", "construction"}
RULES = [  # first match wins, most specific first
    ("security", r"\b(shoot|shot|gunfire|vandal|sabotag|attack|intruder|break-?in|copper theft|stolen|drone|threat)\w*"),
    ("supply_chain", r"\b(transformer shortage|lead times?|supply chain|backlog|tariffs?|procurement|shortage of)\b"),
    ("opposition", r"\b(oppos\w+|residents? (?:fight|push back|object)|lawsuit|sued?|suing|superior court|court fight|protest\w*|petition|eminent domain|condemn\w+|landowners?|not in my|route (?:change|fight)|public comment)\b"),
    ("delay", r"\b(delay\w*|postpon\w*|pushed back|behind schedule|on hold|paused|setback|slip\w*|later than planned|halt\w*|suspend\w*)\b"),
    ("damage", r"\b(damag\w+|destroy\w+|downed|toppl\w+|knocked out|explosion|explode\w*|fire at|substation fire|caught fire|burn\w+|collaps\w+|struck)\b"),
    ("outage", r"\b(outages?|without power|lost power|blackout|power (?:is )?out|restor\w+ power|restoration)\b"),
    ("regulatory", r"\b(public service commission|public utilities? commission|psc\b|puc\b|ferc|docket|rate case|rate hike|approv\w+|certificate|cpcn|"
                   r"siting|permit\w*|environmental review|hearing|regulator\w*|commission(?:ers)? vot\w+|order\w*)\b"),
    ("funding", r"\b(grant\w*|funding|funded|\bdoe\b|department of energy|bond\w*|financ\w+|budget|investment|invest\w+ \$)\b"),
    ("construction", r"\b(under construction|broke ground|groundbreaking|crews? (?:are|were|will|began|begin)|completed|energiz\w+|in service|"
                     r"construction (?:begins|started|starts|underway)|rebuild\w*|upgrade\w*|new (?:transmission )?line|substation)\b"),
]
COMPILED = [(k, re.compile(p, re.I)) for k, p in RULES]
SENTENCE = re.compile(r"(?<=[.!?])\s+")
LLM_SCHEMA = {"type": "object", "properties": {"impact": {"type": "string", "enum": IMPACTS}, "affects_work": {"type": "boolean"},
                                              "summary": {"type": "string"}}, "required": ["impact", "affects_work", "summary"]}
LLM_PROMPT = """You classify a news story for an electric utility's construction planners. Reply with JSON only.
impact: one of delay, damage, outage, opposition, regulatory, supply_chain, security, funding, construction, other.
affects_work: true if the story could change when, where or how transmission construction crews work.
summary: one sentence copied or closely paraphrased from the text, at most 200 characters, no facts that are not in the text."""
_llm_calls = {"n": 0}


def impact_of(text):
    """Rule-based impact and the words that decided it."""
    for kind, rx in COMPILED:
        m = rx.search(text or "")
        if m:
            return kind, m.group(0)
    return "other", None


def _term_rx(term):
    return re.compile(r"(?<![A-Za-z0-9&])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)


def link(article, lexicon):
    """Which utilities and projects a story names. lexicon: org -> {org, state, station, county}."""
    text = f"{article.get('title') or ''}. {article.get('description') or ''} {article.get('text') or ''}"
    title = article.get("title") or ""
    org_ids, job_ids, evidence = [], set(), {"org": [], "station": [], "county": []}
    in_title = False
    for org, lx in lexicon.items():
        hit = [n for n in lx["org"] if _term_rx(n).search(text)]
        if not hit:
            continue
        org_ids.append(org)
        evidence["org"] += hit
        in_title = in_title or any(_term_rx(n).search(title) for n in hit)
        state_named = bool(lx.get("state")) and bool(_term_rx(lx["state"]).search(text))
        for term, jobs in lx["station"].items():
            if _term_rx(term).search(text):
                job_ids.update(jobs)
                evidence["station"].append(term)
        for term, jobs in lx["county"].items():
            if state_named and re.search(rf"\b{re.escape(term)}\s+(county|parish)\b", text, re.I):  # a county only counts with its state
                job_ids.update(jobs)
                evidence["county"].append(term)
    if not org_ids:
        return None
    conf = 0.5 + (0.15 if in_title else 0) + min(0.2, 0.1 * len(evidence["station"])) + min(0.1, 0.05 * len(evidence["county"]))
    return {"org_ids": sorted(set(org_ids)), "job_ids": sorted(job_ids), "evidence": {k: sorted(set(v)) for k, v in evidence.items() if v},
            "confidence": round(min(conf, 0.95), 2)}


def summary_of(article, keyword=None):
    """The first sentence that carries the impact keyword or the utility's name, from the story itself; never written by us."""
    text = article.get("text") or article.get("description") or ""
    sentences = [s.strip() for s in SENTENCE.split(text) if len(s.strip()) > 20]
    picks = [s for s in sentences if keyword and re.search(re.escape(keyword), s, re.I)] or sentences[:1]
    if not picks:
        return None  # nothing beyond the headline; the UI shows the title alone
    s = picks[0].strip()
    return (s[:197] + "...") if len(s) > 200 else s


def llm_classify(article):
    """Gemini for the stories rules could not place; capped per run and validated against the text."""
    cap = int(os.environ.get("NEWS_LLM_MAX") or 10)
    if _llm_calls["n"] >= cap:
        return None
    from app.llm import generate_json, provider
    if not provider():
        return None
    _llm_calls["n"] += 1
    text = (article.get("text") or article.get("description") or "")[:6000]
    try:
        out = json.loads(generate_json(f"{LLM_PROMPT}\n\nTitle: {article.get('title')}\n\n{text}", LLM_SCHEMA) or "{}")
    except Exception:
        return None
    if out.get("impact") not in IMPACTS:
        return None
    words = set(norm(out.get("summary", "")).split())
    known = set(norm(f"{article.get('title')} {text}").split())
    if len(words) < 4 or len(words & known) / len(words) < 0.7:  # the summary must come from the story
        out["summary"] = None
    return out


def classify(article, lexicon, allow_llm=True):
    """Full classification of one article, or None when it names none of our utilities."""
    linked = link(article, lexicon)
    if not linked:
        return None
    haystack = f"{article.get('title') or ''}. {article.get('description') or ''} {article.get('text') or ''}"
    impact, keyword = impact_of(haystack)
    by = "rules"
    summary = summary_of(article, keyword or (linked["evidence"].get("org") or [None])[0])
    if impact == "other" and allow_llm:
        got = llm_classify(article)
        if got:
            impact, by = got["impact"], "gemini"
            summary = got.get("summary") or summary
    return {**linked, "impact": impact, "affects_work": impact in AFFECTS_WORK, "summary": summary, "classified_by": by,
            "evidence": {**linked["evidence"], **({"keyword": keyword} if keyword else {})}}
