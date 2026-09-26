import csv
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel, ValidationError, field_validator

from app.db import ROOT
from app.geo import nominatim
from app.llm import MODEL
from app.storm.incidents import POWER_KINDS, classify, customers, domain, utility

NEWS = ROOT / "data/raw/helene/news"
GKG = "https://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip"
LASTUPDATE = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)"}
REPLAY_SPAN = (datetime(2024, 9, 25, 12, tzinfo=timezone.utc), datetime(2024, 9, 29, 0, tzinfo=timezone.utc))
REGION = (-82.8, 31.8, -80.4, 34.0)  # Augusta, Aiken, Savannah, Beaufort along the river
POWER_THEMES = re.compile(r"POWER_OUTAGE|WITHOUT_POWER|KNOCKED_OUT_POWER|DOWNED_POWER_LINES|POWER_LINES")
KINDS = ["downed_line", "substation_damage", "outage", "tree_on_line", "flooding", "wind_damage"]
SENTENCE = re.compile(r"(?<=[.!?])\s+")
SCHEMA = {"type": "object", "properties": {"incidents": {"type": "array", "items": {"type": "object", "properties": {
    "what": {"type": "string", "enum": KINDS}, "where_text": {"type": "string"}, "when": {"type": "string"},
    "utility_mentioned": {"type": "string"}, "customers_affected": {"type": "integer"}, "quote_evidence": {"type": "string"}},
    "required": ["what", "where_text", "quote_evidence"]}}}, "required": ["incidents"]}
PROMPT = """Extract grid damage incidents from this news article about Hurricane Helene. One entry per distinct place and kind of damage.
Only use facts stated in the article. Leave a field out if the article does not state it; never guess.
where_text: the most specific place stated (road + town + county + state if given). when: ISO time if stated.
quote_evidence: copy one sentence from the article, word for word, that supports the incident."""


# ---------- collect ----------

def in_region(lon, lat):
    return REGION[0] <= lon <= REGION[2] and REGION[1] <= lat <= REGION[3]


def gkg_rows(text):
    """Filter a GKG 2.1 file to power-damage articles that name a Georgia or South Carolina town in the region."""
    csv.field_size_limit(10 ** 9)
    out = []
    for r in csv.reader(io.StringIO(text), delimiter="\t"):
        if len(r) < 27 or not POWER_THEMES.search(r[7] + ";" + r[8]):
            continue
        places = []
        for loc in r[10].split(";"):
            f = loc.split("#")
            if len(f) >= 9 and f[0] == "3" and f[3] in ("USGA", "USSC") and f[5] and f[6] and in_region(float(f[6]), float(f[5])):
                places.append({"full": f[1], "name": f[1].split(",")[0], "lat": float(f[5]), "lon": float(f[6]), "adm1": f[3]})
        if not places:
            continue
        title = re.search(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", r[26])
        out.append({"url": r[4], "date": r[1], "domain": r[3] or domain(r[4]), "title": title.group(1) if title else "",
                    "themes": sorted({t.split(",")[0] for t in (r[7] + ";" + r[8]).split(";") if POWER_THEMES.search(t)}),
                    "places": list({p["full"]: p for p in places}.values())})
    return out


def fetch_gkg(stamp):
    path = NEWS / "gkg" / f"{stamp}.json"
    if path.exists():
        return json.loads(path.read_text())
    r = httpx.get(GKG.format(stamp=stamp), headers=HEADERS, timeout=120, follow_redirects=True)
    if r.status_code != 200:
        return []
    z = zipfile.ZipFile(io.BytesIO(r.content))
    rows = gkg_rows(z.read(z.namelist()[0]).decode("utf-8", errors="ignore"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))  # keep only the filtered rows, not the 6 MB zip
    return rows


def fetch_article(url):
    path = NEWS / "articles" / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists():
        return json.loads(path.read_text())
    text = None
    try:
        import trafilatura
        r = httpx.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=15, follow_redirects=True)
        if r.status_code == 200:
            text = trafilatura.extract(r.text, include_comments=False, include_tables=False)
    except Exception:
        text = None  # dead links and paywalls fall back to the title
    art = {"url": url, "text": text}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(art))
    return art


GENERIC = re.compile(r"River|Department|Lake|Airport", re.I)  # gdelt places that are not towns


def collect_replay(step_hours=1, max_articles=250):
    """Hourly GKG samples over the replay window, then article text for the matching urls."""
    rows, t = {}, REPLAY_SPAN[0]
    while t < REPLAY_SPAN[1]:
        for row in fetch_gkg(t.strftime("%Y%m%d%H%M%S")):
            places = [p for p in row["places"] if not GENERIC.search(p["name"])]
            if places:
                rows.setdefault(row["url"], {**row, "places": places})
        t += timedelta(hours=step_hours)
    landfall = "20240926120000"  # after the storm reached the region first
    picked = sorted(rows.values(), key=lambda r: (r["date"] < landfall, r["date"]))[:max_articles]
    for row in picked:
        fetch_article(row["url"])
    (NEWS / "replay_rows.json").write_text(json.dumps(picked))
    return len(picked)


# ---------- extract ----------

class Extracted(BaseModel):
    what: str
    where_text: str
    quote_evidence: str
    when: str | None = None
    utility_mentioned: str | None = None
    customers_affected: int | None = None

    @field_validator("what")
    @classmethod
    def known_kind(cls, v):
        if v not in KINDS:
            raise ValueError(f"unknown kind {v}")
        return v

    @field_validator("where_text", "quote_evidence")
    @classmethod
    def not_blank(cls, v):
        if len(v.strip()) < 3:
            raise ValueError("blank")
        return v.strip()


def squash(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _llm(prompt):
    from google import genai
    from google.genai import types
    config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=SCHEMA, temperature=0)
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"]).models.generate_content(model=MODEL, contents=prompt, config=config).text


def llm_extract(row, text):
    """Gemini reads the article; code validates the schema and that the quote really is in the article."""
    raw = json.loads(_llm(f"{PROMPT}\n\nTitle: {row['title']}\n\n{text}") or "{}")
    ok, rejected = [], []
    for item in raw.get("incidents", [])[:8]:
        try:
            e = Extracted(**item)
        except ValidationError as err:
            rejected.append({"item": item, "reason": str(err)[:200]})
            continue
        if squash(e.quote_evidence) not in squash(text):
            rejected.append({"item": item, "reason": "quote not found in article"})  # no invented evidence
            continue
        ok.append(e)
    return ok, rejected


def rule_extract(row, text):
    """No-key fallback: keep a sentence only if it names a region town from GDELT and states power damage."""
    out = []
    for sentence in SENTENCE.split(text or "") + [row["title"]]:
        kind = classify(sentence)
        if kind not in POWER_KINDS:
            continue
        for p in row["places"]:
            if re.search(rf"\b{re.escape(p['name'])}\b", sentence):
                out.append((p, kind, sentence.strip()[:300]))
    return list({(p["full"], k): (p, k, s) for p, k, s in out}.values())


def row_time(row):
    return datetime.strptime(row["date"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def parse_when(value, fallback):
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (AttributeError, ValueError):
        return fallback


def place_point(where_text, row):
    """Geocode with Nominatim (code, not AI); fall back to a GDELT town named in the text."""
    hit = nominatim.lookup(where_text)
    if hit and in_region(float(hit["lon"]), float(hit["lat"])):
        return float(hit["lon"]), float(hit["lat"]), nominatim.precision(hit)
    for p in row["places"]:
        if p["name"].lower() in where_text.lower():
            return p["lon"], p["lat"], "town"
    return None


def items_for(row, text, use_llm=None):
    use_llm = bool(os.environ.get("GEMINI_API_KEY")) if use_llm is None else use_llm
    ts, body = row_time(row), text or row["title"]
    source = {"type": "news", "name": row["domain"], "url": row["url"], "title": row["title"], "ts": ts.isoformat()}
    items = []
    if use_llm:
        extracted, _ = llm_extract(row, body)
        for e in extracted:
            pt = place_point(e.where_text, row)
            if not pt:
                continue  # no trustworthy location, drop it
            items.append({"ts": parse_when(e.when, ts), "kind": e.what, "lon": pt[0], "lat": pt[1], "where_text": e.where_text,
                          "precision": pt[2], "utility_mentioned": e.utility_mentioned, "customers_affected": e.customers_affected,
                          "sources": [{**source, "quote_evidence": e.quote_evidence, "method": "gemini"}]})
        return items
    for p, kind, sentence in rule_extract(row, body):
        items.append({"ts": ts, "kind": kind, "lon": p["lon"], "lat": p["lat"], "where_text": p["full"], "precision": "town",
                      "utility_mentioned": utility(sentence), "customers_affected": customers(sentence),
                      "sources": [{**source, "quote_evidence": sentence, "method": "rules"}]})
    return items


def replay_items():
    """Incident items from cached news only; run scripts.fetch_news first to collect."""
    path = NEWS / "replay_rows.json"
    if not path.exists():
        return []
    items = []
    for row in json.loads(path.read_text()):
        art = fetch_article(row["url"])
        items += items_for(row, art.get("text"))
    return items


def latest_rows(files=4):
    """Live: the newest GKG 15-minute files (no rate limit, unlike the DOC API)."""
    r = httpx.get(LASTUPDATE, headers=HEADERS, timeout=30)
    last = next((l.split()[-1] for l in r.text.splitlines() if l.endswith(".gkg.csv.zip")), None)
    if not last:
        return []
    stamp = datetime.strptime(re.search(r"(\d{14})", last).group(1), "%Y%m%d%H%M%S")
    rows = []
    for k in range(files):
        rows += fetch_gkg((stamp - timedelta(minutes=15 * k)).strftime("%Y%m%d%H%M%S"))
    return rows
