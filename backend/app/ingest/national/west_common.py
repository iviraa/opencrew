"""Station names out of western project titles and prose, shared by the western loaders."""
import re
import subprocess
from datetime import date

from app.db import ROOT
from app.ingest.national.common import county_centroids, find_station

MW = re.compile(r"\b\d+(?:\.\d+)?\s*(?:MW|MVA|MVAR)\b", re.I)
KV = re.compile(r"\b\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*\s*-?\s*kv\b", re.I)
VERB = re.compile(r"^(build|construct|rebuild|reconductor|loop|install|convert|reconfigure|add|replace|upgrade|energize|expand)\s+(a\s+|the\s+)?(new\s+)?", re.I)
STOP = re.compile(r"\b(lines?|reconduct\w*|rebuild|recabl\w*|reinforcement|mitigation|project|substations?|switchyard|switching|stations?|transformers?|"
                  r"bank|bus(es)?|upgrades?|replacements?|addition|area|system|voltage|short|conversion|conversation|phase|capacity|expansion|"
                  r"improvements?|retirement|interconnection|tap|breakers?|series|corridor|development|circuit|install\w*|double|single|"
                  r"distribution|equipment|collector|reliability|resiliency|facility|facilities|support|spare|sectionalizing|shifter|move|solar|wind|"
                  r"no\.?\s*\d+|\d+\s*(and|&)\s*\d+|into|loop|in-and-out|in and out|ac|dc)\b|#\s*\d+", re.I)
UTIL = re.compile(r"\b(bpa|pge|srp|aps|pse|ipc|pacificorp|pg&e)\b|\([^)]*\)", re.I)
DASH = re.compile(r"\s*[-–—]\s*|\s+to\s+", re.I)
PAIR = re.compile(r"\b\d{2,3}(?:\s*[-/]\s*\d{2,3})+\s*kv\b", re.I)  # "345-138 kV" is one voltage, not two stations
TAIL = re.compile(r"\s+(new|from|at|near|in)\b", re.I)  # "Bannock Creek from 46kV", "Crossroads station in Jerome"
STATION = re.compile(r"((?:[A-Z][A-Za-z0-9.'&]*[ -]){1,3})(?:\d+(?:/\d+)*\s*kV\s+)?(?:[Ss]ubstation|[Ss]witchyard|[Ss]witching [Ss]tation|[Ss]tation)\b")
NOT_NAMES = {"the", "new", "existing", "this", "a", "an", "future", "our", "its", "that", "each", "both", "same", "nearby", "proposed", "planned"}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                                         "november", "december"], 1)}


def title_ends(title):
    """'Borden-Storey 230 kV Line Reconductoring' -> ['Borden', 'Storey']; 'Estrella Substation Project' -> ['Estrella']."""
    t = PAIR.sub(" 100 kV ", UTIL.sub(" ", str(title or "")))  # keep a plain kV marker so the name is cut there
    t = re.split(r"\s+(?:and|&)\s+|,", t)[0]  # first facility only
    t = VERB.sub("", t.strip())
    pieces = []
    for piece in DASH.split(t):
        while (lead := STOP.match(piece.strip())):  # "Project Quasar" names the place after the generic word
            piece = piece.strip()[lead.end():]
        cut = min([m.start() for m in (KV.search(piece), STOP.search(piece), MW.search(piece), TAIL.search(piece)) if m] + [len(piece)])
        name = " ".join(piece[:cut].split()).strip(" .-")
        if len(re.sub(r"[^A-Za-z]", "", name)) >= 3:
            pieces.append(name)
    return pieces[-2:] if len(pieces) > 2 else pieces


def text_stations(text):
    """Capitalized names written before 'substation', 'station' or 'switchyard' in prose, in order of first mention."""
    out = []
    for m in STATION.finditer(str(text or "")):
        words = m.group(1).split()
        while words and words[0].lower() in NOT_NAMES:
            words = words[1:]
        name = " ".join(words).strip(" -")
        if len(re.sub(r"[^A-Za-z]", "", name)) >= 3 and name.lower() not in {s.lower() for s in out}:
            out.append(name)
    return out


def pick_ends(title, text, states):
    """Title stations when any of them is on the map, else the first stations named in the text, else the title's (for review)."""
    first = title_ends(title)
    if any(find_station(e, states) for e in first):
        return first
    named = [n for n in text_stations(text) if find_station(n, states)][:2]
    return named or first


def counties_in(text, state):
    """County names in prose ('Whatcom and Skagit counties', 'King County') that exist in the state."""
    known = {name for st, name in county_centroids() if st == state}
    found = []
    for m in re.finditer(r"((?:[A-Z][a-z]+ )?[A-Z][a-z]+)(?: and ((?:[A-Z][a-z]+ )?[A-Z][a-z]+))? [Cc]ount(?:y|ies)\b", str(text or "")):
        for g in m.groups():
            for cand in ([g, g.split()[-1]] if g else []):
                if cand.lower() in known and cand not in found:
                    found.append(cand)
                    break
    return found


def year_end(year):
    return date(int(year), 12, 1)  # a year-only date means sometime that year: plan it done by December


def month_year(text):
    """Every 'June 2026', 'June 30, 2028', '12/2027', '11/15/2027' date in the text."""
    out = []
    for m in re.finditer(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:\d{1,2},\s*)?(20\d\d)\b", text):
        out.append(date(int(m.group(2)), MONTHS[m.group(1).lower()], 1))
    for m in re.finditer(r"\b(\d{1,2})/(?:(\d{1,2})/)?(20\d\d)\b", text):
        out.append(date(int(m.group(3)), int(m.group(1)), int(m.group(2) or 1)))
    return out


def pdf_text(rel):
    """pdftotext -layout of a source pdf, cached next to it."""
    pdf = ROOT / rel
    txt = pdf.with_suffix(".layout.txt")
    if not txt.exists():
        subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=True)
    return txt.read_text(errors="replace")


def kv_of(text):
    m = re.search(r"(\d{2,3})(?:/\d+)*\s*-?\s*kV", str(text or ""), re.I)
    return int(m.group(1)) if m else None


def manifest(state, path="data/raw/national/manifest_west.json"):
    import json
    return next(m for m in json.loads((ROOT / path).read_text()) if m["state"] == state)


def start_org(conn, state, planner, title, edition):
    """Register the state's utility and its source file; returns (org id, source doc id) with the old load cleared."""
    from app.ingest.national.common import clear, register_org, register_source
    m = manifest(state)
    org = m["slug"]
    register_org(conn, org, m["utility"], m["utility"].split(" (")[0].split(" / ")[0], state, planner, org)
    clear(conn, org)
    return org, register_source(conn, org, title, m["url"], m["file"], planner, edition)


def run(conn, org, doc, projects):
    """Save each normalized project; returns placed/review counts."""
    from app.ingest.national.common import save
    counts = {"placed": 0, "review": 0}
    for p in projects:
        counts[save(conn, {**p, "org_id": org}, doc)] += 1
    return counts
