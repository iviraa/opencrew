import re

PREFIX = re.compile(r"^\s*(?:(?:SAV|GTC|MEAG|DU|GRID|CC)\s*[:\-]\s*)+", re.I)  # zone and customer-connection prefixes
EQUIPMENT = re.compile(
    r"\b(statcom|system|bus(es)?|jumpers?|replacement|replace|relay(ing)?|modernization|reactors?|removal|bank\s+[a-z]\b|bank|new|auto|"
    r"transformers?|breakers?|and|half|installation|install|cap|capacitor|protective|equipment|upgrades?|improvements?|improvmnt|"
    r"strategic|solution|project|build|low|side|smart|valves?|panels?|two|stage|dual|network|transmission|needs|solutions?|"
    r"switching|station|sub(station)?|line|lines|rebuild|reconductor|construct|tap|fold-in|at|the|of|cc|kv|area|customer|aka)\b", re.I)
KV = re.compile(r"\b\d{2,3}(?:\s*/\s*\d{2,3})?\s*kv\b|\b\d{2,3}\b|\b\d{2}o\b", re.I)  # "23O kV" is a typo in the filing
MENTION = re.compile(  # "at Anthony Shoals 230kV substation", "inside the Eatonton Primary substation", "the new Garrett Road 230kV switching station"
    r"(?:at|inside|into|of|named|new|the)\s+(?:the\s+|new\s+)?((?:[A-Z][\w.'&#]*\s?){1,4}?)\s*(?:\d{2,3}(?:/\d{2,3})?\s*kV\s+)?"
    r"(?:substation|switching station|station|sub\b|primary substation)")
COUNTY = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?) County\b")


def clean(name):
    """Station name hidden in a project title: 'RICE HOPE NEW AUTO TRANSFORMER' -> 'RICE HOPE'."""
    s = PREFIX.sub("", name or "")
    s = re.sub(r"\(.*?\)", " ", s)
    s = KV.sub(" ", s)
    s = EQUIPMENT.sub(" ", s)
    s = re.sub(r"[^A-Za-z0-9#' ]", " ", s)
    return " ".join(s.split()).strip()


def endpoint_names(job):
    out = []
    for e in job.get("endpoints") or [job["name"]]:
        parts = re.split(r"\s+(?:AND|&)\s+", e) if "-" not in e else [e]  # "THALMANN AND COLERAIN" names two stations
        for part in parts:
            c = clean(part)
            if c and len(c) >= 3 and c.lower() not in {"cc", "grid", "sav"} and c not in out:
                out.append(c)
    if not out:
        c = clean(job["name"])
        if len(c) >= 3:
            out.append(c)
    return out[:2]


def mentioned_stations(text):
    """Station names a filing description names outright, kept whole ("Line Creek" stays "Line Creek")."""
    seen = []
    for m in MENTION.finditer(text or ""):
        n = " ".join(re.sub(r"[^A-Za-z0-9#' ]", " ", KV.sub(" ", m.group(1))).split())
        if len(n) >= 3 and n not in seen:
            seen.append(n)
    return seen[:4]


def counties(text):
    return list(dict.fromkeys(COUNTY.findall(text or "")))


def stated_full_miles(text):
    """Line length the filing states for the whole line, or None when it only describes a segment."""
    t = text or ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mile|mi\b)", t, re.I)
    if not m:
        return None
    around = t[max(0, m.start() - 60): m.end() + 60].lower()
    if re.search(r"section|segment|portion|of the .* line|from .* jct|junction|tap", around):
        return None  # a rebuilt piece, not the whole line
    return float(m.group(1))


OTHER_UTILITY = re.compile(r"\((APC|USA|GTC|MEAG|DU|SCE&G|SCPSA)\)", re.I)  # endpoints owned by someone else


def foreign(endpoint):
    return bool(OTHER_UTILITY.search(endpoint or ""))
