"""Public news search per utility: GDELT's article list and Google News RSS, cached, at most one request a second."""
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

SOURCES = {
    "gdelt_doc": {"title": "GDELT 2.1 DOC API, article list", "url": "https://api.gdeltproject.org/api/v2/doc/doc"},
    "google_news": {"title": "Google News RSS search", "url": "https://news.google.com/rss/search"},
}
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon; news for utility coordination)"}
WORK_TERMS = '(transmission OR substation OR outage OR "power line" OR crews OR restoration OR construction OR project OR permit OR "public service commission")'
_last = {}  # provider -> time of the last request
SPACING = {"gdelt_doc": 5.5, "google_news": 1.0}  # gdelt asks for one request every 5 seconds
SKIPPED = set()  # providers that rate-limited us this run


def _polite(provider):
    wait = SPACING.get(provider, 1.0) - (time.time() - _last.get(provider, 0.0))
    if wait > 0:
        time.sleep(wait)
    _last[provider] = time.time()


def _get(url, params, provider):
    if provider in SKIPPED:
        return None
    for attempt in range(3):
        _polite(provider)
        try:
            r = httpx.get(url, params=params, headers=HEADERS, timeout=30, follow_redirects=True)
        except httpx.HTTPError:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            return r
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        break
    SKIPPED.add(provider)  # leave this provider alone for the rest of the run
    return None


def gdelt(name, days=90, limit=75):
    """Articles naming the utility and work words, newest first."""
    q = f'"{name}" {WORK_TERMS} sourcecountry:US'
    r = _get(SOURCES["gdelt_doc"]["url"], {"query": q, "mode": "artlist", "format": "json", "timespan": f"{min(days, 90)}d",
                                          "maxrecords": limit, "sort": "datedesc"}, "gdelt_doc")
    if not r or not r.text.strip().startswith("{"):
        return []
    out = []
    for a in r.json().get("articles", []):
        try:
            when = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            when = None
        out.append({"url": a.get("url"), "title": html.unescape(a.get("title") or ""), "source": a.get("domain"), "published": when,
                    "description": "", "provider": "gdelt_doc", "query": name})
    return [o for o in out if o["url"] and o["title"]]


def google_news(name, days=90):
    q = f'"{name}" {WORK_TERMS} when:{min(days, 365)}d'
    r = _get(SOURCES["google_news"]["url"], {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}, "google_news")
    if not r:
        return []
    out = []
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return []
    for it in root.iter("item"):
        title = html.unescape(it.findtext("title") or "")
        src = it.find("source")
        source = (src.text if src is not None else None) or ""
        title = re.sub(rf"\s+-\s+{re.escape(source)}$", "", title) if source else title
        try:
            when = parsedate_to_datetime(it.findtext("pubDate") or "")
        except (TypeError, ValueError):
            when = None
        desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        out.append({"url": it.findtext("link"), "title": title, "source": source or "Google News", "published": when,
                    "description": re.sub(r"\s+", " ", desc).strip()[:500], "provider": "google_news", "query": name})
    return [o for o in out if o["url"] and o["title"]]


def search(names, days=90):
    """Every article for a utility's names across providers, deduped by url."""
    seen, out = set(), []
    for n in names:
        for art in gdelt(n, days) + google_news(n, days):
            if art["url"] not in seen:
                seen.add(art["url"])
                out.append(art)
    return out


def cache(conn, articles):
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO news_raw (url, source, payload) VALUES (%s, %s, %s)
                           ON CONFLICT (url) DO UPDATE SET fetched_at = now(), payload = EXCLUDED.payload""",
                        [(a["url"], a["provider"], json.dumps({**a, "published": a["published"].isoformat() if a["published"] else None})) for a in articles])
