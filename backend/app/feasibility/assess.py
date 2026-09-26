"""Run every factor, combine them into one verdict, write a short narrative and keep the result for a day."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from app.feasibility import cost, counterparty, forecast, future, location, news, timing
from app.feasibility.common import verdict_for
from app.feasibility.data import gather, overlap_row

FACTORS = [("location", location, 0.2), ("timing", timing, 0.25), ("cost", cost, 0.2), ("forecast", forecast, 0.1),
           ("news", news, 0.1), ("counterparty", counterparty, 0.05), ("future", future, 0.1)]
FRESH_H = 24
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS feasibility_assessment (
  id             SERIAL PRIMARY KEY,
  opportunity_id INT NOT NULL,
  company_id     TEXT NOT NULL,
  verdict        TEXT NOT NULL,
  score          REAL NOT NULL,
  factors        JSONB NOT NULL,
  narrative      TEXT,
  fingerprint    TEXT,
  quick          BOOLEAN DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT now(),
  UNIQUE (opportunity_id, company_id)
)"""
UPSERT_SQL = """
INSERT INTO feasibility_assessment (opportunity_id, company_id, verdict, score, factors, narrative, fingerprint, quick, created_at)
VALUES (%(opportunity_id)s, %(company_id)s, %(verdict)s, %(score)s, %(factors)s, %(narrative)s, %(fingerprint)s, %(quick)s, now())
ON CONFLICT (opportunity_id, company_id) DO UPDATE SET verdict = EXCLUDED.verdict, score = EXCLUDED.score, factors = EXCLUDED.factors,
  narrative = EXCLUDED.narrative, fingerprint = EXCLUDED.fingerprint, quick = EXCLUDED.quick, created_at = now()
"""


def combine(factors):
    """Weighted score over the factors that could be judged; any 'unlikely' caps the verdict, two make it unlikely."""
    known = [(f, w) for (name, _, w), f in zip(FACTORS, factors) if f["score"] is not None]
    if not known:
        return "unknown", 0.0
    score = sum(f["score"] * w for f, w in known) / sum(w for _, w in known)
    verdict = verdict_for(score)
    bad = sum(1 for f in factors if f["verdict"] == "unlikely")
    if bad >= 2:
        verdict = "unlikely"
    elif bad == 1 and verdict == "strong":
        verdict = "possible"
    return verdict, round(score, 2)


def template_narrative(ctx, verdict, factors):
    """Three plain sentences built only from factor evidence, used when no model is available or its numbers don't check out."""
    by = {f["factor"]: f for f in factors}
    lead = {"strong": "looks strong", "possible": "is possible with conditions", "unlikely": "looks unlikely as things stand", "unknown": "could not be judged yet"}[verdict]
    first = f"Overlap #{ctx['op']['id']} with {ctx['partner']} {lead}."
    good = [f["evidence"][0] for f in factors if f["verdict"] == "strong" and f["evidence"]][:2]
    weak = [f["evidence"][0] for f in factors if f["verdict"] == "unlikely" and f["evidence"]][:2]
    second = ("In its favor: " + "; ".join(good) + ".") if good else ("Working against it: " + "; ".join(weak) + ".") if weak else (by["timing"]["evidence"][0] + ".")
    conds = [c for f in factors for c in f["conditions"]][:2]
    third = ("What would make it work: " + "; ".join(conds) + ".") if conds else "Nothing stands out as a blocker."
    return " ".join((first, second, third))


def llm_narrative(ctx, verdict, factors):
    """A model writes the same three sentences from the factor JSON alone; any number not in that JSON sends us back to the template."""
    from app.llm import generate, provider, unsourced
    if not provider():
        return None
    facts = json.dumps({"overlap": ctx["op"]["id"], "partner": ctx["partner"], "verdict": verdict,
                        "factors": [{k: f[k] for k in ("factor", "verdict", "evidence", "conditions")} for f in factors]}, default=str)
    prompt = ("Write exactly three short plain sentences for a utility planner about whether coordinating this overlap with the partner "
              "utility is feasible. Use only the facts below; never add numbers that are not in them; no advice about sending crews. "
              "Sentence 1: the verdict and why. Sentence 2: the main risk or strength. Sentence 3: what would make it work.\n" + facts)
    try:
        text = generate(prompt).strip()
    except Exception:
        return None
    return text if text and not unsourced(text, facts) else None


def fingerprint(op, ctx):
    key = json.dumps([op["score"], op["savings_high"], str(op["a_end"]), str(op["b_end"]), op.get("status"),
                      len(ctx.get("requests") or []), len(ctx.get("news") or [])], default=str)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def as_result(row):
    return {"opportunity_id": row["opportunity_id"], "company_id": row["company_id"], "verdict": row["verdict"], "score": row["score"],
            "factors": row["factors"], "narrative": row["narrative"], "quick": row.get("quick", False),
            "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"]}


def build(ctx, quick=False, use_llm=True):
    """Assessment from a gathered context; no database, so tests can feed synthetic rows."""
    factors = [mod.assess(ctx) for _, mod, _ in FACTORS]
    verdict, score = combine(factors)
    narrative = (llm_narrative(ctx, verdict, factors) if use_llm and not quick else None) or template_narrative(ctx, verdict, factors)
    return {"opportunity_id": ctx["op"]["id"], "company_id": ctx["company"], "partner": ctx["partner"], "verdict": verdict, "score": score,
            "factors": factors, "narrative": narrative, "quick": quick}


def assess(conn, opportunity_id, company_id, refresh=False, quick=False, today=None):
    """The stable entry point: a cached assessment when fresh and unchanged, otherwise a new one. None if the overlap isn't the company's."""
    conn.execute(TABLE_SQL)
    op = overlap_row(conn, opportunity_id, company_id)
    if not op:
        return None
    row = conn.execute("SELECT * FROM feasibility_assessment WHERE opportunity_id = %s AND company_id = %s", (int(opportunity_id), company_id)).fetchone()
    if row and not refresh:
        age = datetime.now(timezone.utc) - row["created_at"]
        if age < timedelta(hours=FRESH_H) and (quick or not row.get("quick")):
            probe = fingerprint(op, {"requests": None, "news": None})[:8]  # cheap part of the print: the overlap row itself
            if (row.get("fingerprint") or "").startswith(probe):
                return as_result(row)
    ctx = gather(conn, op, company_id, quick=quick, today=today)
    out = build(ctx, quick=quick)
    fp = fingerprint(op, {"requests": None, "news": None})[:8] + fingerprint(op, ctx)[8:]
    conn.execute(UPSERT_SQL, {"opportunity_id": int(opportunity_id), "company_id": company_id, "verdict": out["verdict"], "score": out["score"],
                              "factors": json.dumps(out["factors"], default=str), "narrative": out["narrative"], "fingerprint": fp, "quick": quick})
    saved = conn.execute("SELECT created_at FROM feasibility_assessment WHERE opportunity_id = %s AND company_id = %s", (int(opportunity_id), company_id)).fetchone()
    return {**out, "created_at": saved["created_at"].isoformat()}


def rank(conn, company_id, candidates, quick=True):
    """Quick assessments for many overlaps: {opportunity_id: (verdict, score)}, cached rows reused."""
    out = {}
    for op in candidates:
        try:
            a = assess(conn, op["id"], company_id, quick=quick)
            if a:
                out[op["id"]] = {"verdict": a["verdict"], "score": a["score"]}
        except Exception:
            conn.rollback()
    return out
