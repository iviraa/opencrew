"""Fetch, classify, link and store news for a utility, and hand the linked items to the rest of the app."""
import hashlib
import ipaddress
import json
import re
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from rapidfuzz import fuzz

from app.db import ROOT
from app.news import classify, fetch, lexicon

ARTICLES = ROOT / "data/layers/news_articles"
PAGE_CAP = 20  # story pages fetched per run, only for linked items
FIELDS = "id, url, title, source, published, impact, affects_work, summary, confidence, org_ids, job_ids, opportunity_ids, verified, evidence, classified_by"


def _public(url):
    host = urlparse(url).hostname or ""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except socket.gaierror:
        return False
    return url.startswith("http")


def page_text(url):
    """Story text for a linked item, cached on disk; dead links and paywalls give None."""
    path = ARTICLES / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text()).get("text")
    text = None
    if _public(url):
        try:
            import trafilatura
            r = httpx.get(url, headers={**fetch.HEADERS, "Accept": "text/html"}, timeout=10, follow_redirects=True)
            if r.status_code == 200 and len(r.content) < 3_000_000:
                text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
        except Exception:
            text = None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"url": url, "text": text}))
    return text


def dedupe(articles):
    """Drop repeats of the same story: same url, or the same headline from another outlet."""
    out = []
    for a in sorted(articles, key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        if any(a["url"] == b["url"] or fuzz.token_set_ratio(a["title"], b["title"]) >= 92 for b in out):
            continue
        out.append(a)
    return out


def opportunities_for(conn, job_ids):
    if not job_ids:
        return []
    rows = conn.execute("SELECT id FROM opportunity WHERE horizon = 'long' AND (job_a = ANY(%s) OR job_b = ANY(%s))", (job_ids, job_ids)).fetchall()
    return sorted({r["id"] for r in rows})


def verify(conn, job_ids, published):
    """True when an official storm report or an incident sits near the linked projects within three days of the story."""
    if not job_ids or not published:
        return False, None
    row = conn.execute("""
        SELECT i.kind, i.ts, i.where_text FROM incident i JOIN job j ON j.id = ANY(%(jobs)s)
        WHERE i.ts BETWEEN %(t)s - interval '3 days' AND %(t)s + interval '3 days' AND ST_DWithin(i.geom, j.geom, 50000)
        ORDER BY abs(extract(epoch FROM i.ts - %(t)s)) LIMIT 1""", {"jobs": job_ids, "t": published}).fetchone()
    if row:
        return True, {"incident": row["kind"], "at": row["ts"].isoformat(), "where": row["where_text"]}
    row = conn.execute("""
        SELECT e.kind, e.ts FROM storm_event e JOIN job j ON j.id = ANY(%(jobs)s)
        WHERE e.ts BETWEEN %(t)s - interval '3 days' AND %(t)s + interval '3 days' AND e.geom IS NOT NULL AND ST_DWithin(e.geom, j.geom, 50000)
        ORDER BY abs(extract(epoch FROM e.ts - %(t)s)) LIMIT 1""", {"jobs": job_ids, "t": published}).fetchone()
    return (True, {"storm_event": row["kind"], "at": row["ts"].isoformat()}) if row else (False, None)


def store(conn, item):
    return conn.execute("""
        INSERT INTO news_item (url, title, source, published, impact, affects_work, summary, confidence, org_ids, job_ids, opportunity_ids,
                               verified, evidence, classified_by)
        VALUES (%(url)s, %(title)s, %(source)s, %(published)s, %(impact)s, %(affects_work)s, %(summary)s, %(confidence)s, %(org_ids)s, %(job_ids)s,
                %(opportunity_ids)s, %(verified)s, %(evidence)s, %(classified_by)s)
        ON CONFLICT (url) DO UPDATE SET impact = EXCLUDED.impact, affects_work = EXCLUDED.affects_work, summary = EXCLUDED.summary,
          confidence = EXCLUDED.confidence, org_ids = EXCLUDED.org_ids, job_ids = EXCLUDED.job_ids, opportunity_ids = EXCLUDED.opportunity_ids,
          verified = EXCLUDED.verified, evidence = EXCLUDED.evidence, classified_by = EXCLUDED.classified_by, fetched_at = now()
        RETURNING id""", {**item, "evidence": json.dumps(item["evidence"])}).fetchone()["id"]


def run(conn, org_ids, days=90, rebuild_lexicon=True, allow_llm=True):
    """One pass for some utilities: search, dedupe, link, classify, verify, store. Returns counts per org."""
    if rebuild_lexicon:
        for o in org_ids:
            lexicon.build(conn, o)
    lx = lexicon.load(conn)  # every utility, so a story about two neighbors links to both
    counts, pages = {}, 0
    for o in org_ids:
        if o not in lx:
            counts[o] = {"fetched": 0, "linked": 0, "impacts": {}}
            continue
        found = dedupe(fetch.search(lx[o]["org"], days))
        fetch.cache(conn, found)
        c = {"fetched": len(found), "linked": 0, "impacts": {}}
        for art in found:
            got = classify.classify(art, lx, allow_llm=False)
            if not got:
                continue
            if pages < PAGE_CAP and "google.com" not in (urlparse(art["url"]).hostname or ""):  # google links redirect through a script
                art["text"] = page_text(art["url"])
                pages += 1
                got = classify.classify(art, lx, allow_llm=allow_llm) or got
            elif got["impact"] == "other" and allow_llm:
                got = classify.classify(art, lx, allow_llm=True) or got
            opps = opportunities_for(conn, got["job_ids"])
            ok, why = verify(conn, got["job_ids"], art["published"])
            item = {**got, "url": art["url"], "title": art["title"], "source": art["source"], "published": art["published"],
                    "opportunity_ids": opps, "verified": ok, "evidence": {**got["evidence"], **({"verified_by": why} if why else {}), "provider": art["provider"]}}
            store(conn, item)
            c["linked"] += 1
            c["impacts"][got["impact"]] = c["impacts"].get(got["impact"], 0) + 1
        counts[o] = c
        print(o, c, flush=True)
    return counts


def _item(r):
    return {"id": r["id"], "title": r["title"], "source": r["source"], "url": r["url"],
            "published": r["published"].isoformat() if r["published"] else None, "impact": r["impact"], "affects_work": r["affects_work"],
            "summary": r["summary"], "confidence": r["confidence"], "org_ids": list(r["org_ids"] or []), "job_ids": list(r["job_ids"] or []),
            "opportunity_ids": list(r["opportunity_ids"] or []), "verified": r["verified"], "evidence": r["evidence"] or {}}


def for_overlap(conn, opportunity_id, days=90):
    """Stories linked to either project of an overlap, or to either utility, newest first; project-linked ones first."""
    op = conn.execute("SELECT job_a, job_b, ja.org_id AS a_org, jb.org_id AS b_org FROM opportunity o JOIN job ja ON ja.id = o.job_a JOIN job jb ON jb.id = o.job_b WHERE o.id = %s",
                      (opportunity_id,)).fetchone()
    if not op:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = conn.execute(f"""SELECT {FIELDS}, (%(id)s = ANY(opportunity_ids)) AS direct FROM news_item
                            WHERE (published IS NULL OR published >= %(since)s) AND (org_ids && %(orgs)s OR %(id)s = ANY(opportunity_ids))
                            ORDER BY direct DESC, affects_work DESC, published DESC NULLS LAST LIMIT 50""",
                        {"id": opportunity_id, "since": since, "orgs": [op["a_org"], op["b_org"]]}).fetchall()
    return [{**_item(r), "direct": r["direct"]} for r in rows]


def for_org(conn, org_id, days=90, impact=None):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = conn.execute(f"""SELECT {FIELDS}, (cardinality(job_ids) > 0) AS direct FROM news_item
                            WHERE (published IS NULL OR published >= %(since)s) AND %(org)s = ANY(org_ids) AND (%(imp)s::text IS NULL OR impact = %(imp)s)
                            ORDER BY direct DESC, affects_work DESC, published DESC NULLS LAST LIMIT 100""",
                        {"org": org_id, "since": since, "imp": impact}).fetchall()
    return [{**_item(r), "direct": r["direct"]} for r in rows]


def one(conn, item_id):
    r = conn.execute(f"SELECT {FIELDS} FROM news_item WHERE id = %s", (item_id,)).fetchone()
    return _item(r) if r else None
