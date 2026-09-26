"""Station names out of southern planners' project titles and terminal fields."""
import hashlib
import re

from app.geo.geolocate import norm

KV = re.compile(r"\s*\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)*\s*kv\b.*$", re.I)  # "230/115 kV Substation" and everything after
VERBS = re.compile(r"^(establish|construct|build|new|add|install|rebuild|upgrade|replace|expand|convert|loop)\s+", re.I)
SPLIT = re.compile(r"\s*[–—]\s*|\s+-\s+|(?<=[A-Za-z])-(?=[A-Za-z])")  # "A – B", "A - B", "A-B"
SUFFIX = re.compile(r"\s+(switch(yard)?|substation|sub|pod|poi|interconnect(ion)?|synchronous condenser|autotransformers?|capacitor bank|"
                    r"reactor|statcom|station|tap|junction|jct|tie|plant|energy center)\b.*$", re.I)  # words osm names rarely carry
JUNK = {"", "generator", "line", "lines", "transmission", "tbd", "various", "n a", "na", "none", "system", "bus"}


def station(name):
    """One terminal cleaned for matching, or None when it is not a place."""
    s = re.sub(r"\s+", " ", str(name or "")).strip()
    s = KV.sub("", s)
    s = re.sub(r"\((?:fka|aka|f/k/a)[^)]*\)", "", s, flags=re.I)
    s = VERBS.sub("", s).strip(" ,.;:")
    s = s.split("/")[0].strip()  # "Pleasant Valley/Fisher Road": either name, take the first
    s = SUFFIX.sub("", s).strip(" ,.;:") or s
    return None if norm(s) in JUNK or len(norm(s)) < 3 else s


def ends_from_title(title):
    """Up to two station names from a title like "A - B 230 kV Line, Rebuild" or "X 115 kV Substation"."""
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    paren = re.search(r"\(([^()]*?[–—-][^()]*?)\)", t)
    head = re.sub(r"\([^()]*\)", " ", KV.sub("", t.split(",")[0]))
    parts = [x for x in (station(p) for p in SPLIT.split(head)) if x]
    if len(parts) < 2 and paren and not re.search(r"\bkv\b", paren.group(1), re.I):  # "Beulah 100 kV Line (Lookout-EnergyUnited Del 18)"
        inner = [x for x in (station(p) for p in SPLIT.split(paren.group(1))) if x]
        if len(inner) == 2:
            parts = inner
    return list(dict.fromkeys(parts))[:2]


def stable_id(prefix, *parts):
    return f"{prefix}-{hashlib.sha1('|'.join(norm(str(p)) for p in parts).encode()).hexdigest()[:10]}"
