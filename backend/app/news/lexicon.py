"""What to search for per utility: its names, the stations and counties its projects sit in, and its state."""
import io
import re
import zipfile
from functools import lru_cache

import shapefile

from app.db import ROOT
from app.geo.geolocate import norm

PARENTS = {  # org -> extra names the press uses (parents, brands, old names)
    "desc": ["Dominion Energy", "Dominion Energy South Carolina", "SCE&G"], "gpc": ["Georgia Power", "Southern Company"],
    "alabamapower": ["Alabama Power", "Southern Company"], "tva": ["TVA", "Tennessee Valley Authority"],
    "duke": ["Duke Energy", "Duke Energy Carolinas", "Duke Energy Progress"], "fpl": ["FPL", "Florida Power & Light", "NextEra"],
    "oncor": ["Oncor"], "xcelmn": ["Xcel Energy", "Northern States Power"], "xcelco": ["Xcel Energy", "Public Service Company of Colorado"],
    "sps": ["Xcel Energy", "Southwestern Public Service"], "entergyar": ["Entergy", "Entergy Arkansas"], "entergyla": ["Entergy", "Entergy Louisiana"],
    "entergyms": ["Entergy", "Entergy Mississippi"], "ppl": ["PPL", "PPL Electric"], "aep-ohio": ["AEP", "AEP Ohio", "American Electric Power"],
    "evergyks": ["Evergy"], "oge": ["OG&E", "Oklahoma Gas & Electric", "Oklahoma Gas and Electric"], "pge": ["PG&E", "Pacific Gas and Electric"],
    "eversource-ct": ["Eversource"], "eversource-ma": ["Eversource"], "eversource-nh": ["Eversource"], "national-grid-ny": ["National Grid"],
    "rockymountainpower": ["PacifiCorp", "Rocky Mountain Power"], "idahopower": ["Idaho Power"], "nvenergy": ["NV Energy"], "aps": ["APS", "Arizona Public Service"],
    "itcmidwest": ["ITC Midwest", "ITC Holdings", "MidAmerican"], "atc": ["American Transmission Company", "ATC"], "metc": ["METC", "ITC Holdings"],
    "amerenil": ["Ameren", "Ameren Illinois"], "amerenmo": ["Ameren", "Ameren Missouri"], "dukein": ["Duke Energy", "Duke Energy Indiana"],
    "basin": ["Basin Electric"], "eastriver": ["East River Electric"], "nppd": ["NPPD", "Nebraska Public Power District"],
    "blackhills": ["Black Hills Energy", "Cheyenne Light"], "bpa": ["BPA", "Bonneville Power Administration"],
    "portlandgeneral": ["Portland General Electric", "PGE"], "pse": ["Puget Sound Energy", "PSE"], "cmp": ["Central Maine Power", "CMP"],
    "rhode-island-energy": ["Rhode Island Energy"], "velco": ["VELCO", "Vermont Electric Power"], "jcpl": ["JCP&L", "Jersey Central Power & Light"],
    "delmarva": ["Delmarva Power"], "potomac-edison": ["Potomac Edison", "FirstEnergy"], "mon-power": ["Mon Power", "FirstEnergy"],
    "ekpc": ["EKPC", "East Kentucky Power Cooperative"], "dominion-va": ["Dominion Energy", "Dominion Energy Virginia"],
}
STATE_NAMES = {"AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
               "FL": "Florida", "GA": "Georgia", "IA": "Iowa", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "KS": "Kansas", "KY": "Kentucky",
               "LA": "Louisiana", "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine", "MI": "Michigan", "MN": "Minnesota", "MO": "Missouri",
               "MS": "Mississippi", "MT": "Montana", "NC": "North Carolina", "ND": "North Dakota", "NE": "Nebraska", "NH": "New Hampshire",
               "NJ": "New Jersey", "NM": "New Mexico", "NV": "Nevada", "NY": "New York", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
               "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
               "UT": "Utah", "VA": "Virginia", "VT": "Vermont", "WA": "Washington", "WI": "Wisconsin", "WV": "West Virginia", "WY": "Wyoming"}
GENERIC = {"north", "south", "east", "west", "central", "new", "old", "lake", "river", "city", "county", "creek", "hill", "park", "main", "union",
           "washington", "lincoln", "jackson", "franklin", "jefferson", "madison", "monroe", "marion", "clay", "grant", "lee", "wayne", "church",
           "center", "school", "mill", "mills", "farm", "ridge", "valley", "springs", "station", "airport", "hospital", "plant", "college", "college"}  # too common to link on alone
KV = re.compile(r"\b\d+(?:\.\d+)?\s*/?\s*(?:\d+\s*)?kv\b.*$", re.I)
WORK = re.compile(r"\b(equipment|replacement|rebuild|upgrade|reconductor|expansion|addition|improvements?|project|line|tie|loop|conversion|"
                  r"install(ation)?|new|construct(ion)?|breaker|transformer|capacitor|reactor|bank|ckt|circuit)\b.*$", re.I)
SUFFIX = re.compile(r"\s+(substation|sub|switchyard|switching station|station|tap|jct|junction|plant|energy center|ehv|primary)\b.*$", re.I)


def station_term(name):
    """A station name as the press would write it, or None when it is too short or generic to link on."""
    s = re.split(r"_x000D_|[\r\n]|#", str(name or ""))[0]  # "Gainesville #2 Equipment Replacement": the station is before the number
    s = WORK.sub("", re.sub(r"\s+", " ", KV.sub("", s))).strip(" ,.;:-")
    s = SUFFIX.sub("", s).strip(" ,.;:-")
    s = re.sub(r"\s*\(.*?\)", "", s).strip()
    words = [w for w in norm(s).split() if w]
    if not words or len(norm(s)) < 5 or all(w in GENERIC for w in words) or (len(words) == 1 and len(words[0]) < 5):
        return None
    return s


@lru_cache
def county_names():
    """GEOID -> (state, name) from the Census 1:20m county file."""
    z = zipfile.ZipFile(ROOT / "data/layers/counties_20m.zip")
    base = next(n for n in z.namelist() if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    return {rec["GEOID"]: (rec["STUSPS"], rec["NAME"]) for rec in r.records()}


def job_counties(conn, org_id):
    """job_id -> county names: the planner's own list when it gave one, else the counties under the mapped works."""
    from app.hazards.exposure import county_fips_for
    rows = conn.execute("SELECT id, counties, ST_AsBinary(geom::geometry) AS wkb FROM job WHERE org_id = %s AND horizon = 'long'", (org_id,)).fetchall()
    names = county_names()
    out = {}
    for r in rows:
        if r["counties"]:
            out[r["id"]] = [re.sub(r"\s+(county|parish)$", "", c.strip(), flags=re.I) for c in r["counties"] if c]
        else:
            try:
                out[r["id"]] = [names[f][1] for f in county_fips_for(conn, r["wkb"]) if f in names]
            except Exception:
                out[r["id"]] = []
    return out


def build(conn, org_id):
    """Rebuild one utility's search terms: names, stations (from project endpoints and titles) and counties."""
    org = conn.execute("SELECT id, name, short, state FROM org WHERE id = %s", (org_id,)).fetchone()
    if not org:
        return 0
    counties_here = {norm(n) for st, n in county_names().values() if st == org["state"]}  # a station named like a county links only as a county
    terms = {}  # (kind, term) -> set(job_ids)
    for n in {org["name"], org["short"], *PARENTS.get(org_id, [])}:
        if n and len(n) >= 3:
            terms.setdefault(("org", n), set())
    if org["state"]:
        terms.setdefault(("state", STATE_NAMES.get(org["state"], org["state"])), set())
    jobs = conn.execute("SELECT id, name, endpoints FROM job WHERE org_id = %s AND horizon = 'long'", (org_id,)).fetchall()
    for j in jobs:
        for e in (j["endpoints"] or []):
            t = station_term(e)
            if t and norm(t) not in counties_here:
                terms.setdefault(("station", t), set()).add(j["id"])
    for jid, counties in job_counties(conn, org_id).items():
        for c in counties:
            if c and norm(c) not in GENERIC:
                terms.setdefault(("county", c), set()).add(jid)
    conn.execute("DELETE FROM news_lexicon WHERE org_id = %s", (org_id,))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO news_lexicon (org_id, kind, term, job_ids) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        [(org_id, k, t, sorted(ids) or None) for (k, t), ids in terms.items()])
    return len(terms)


def load(conn, org_ids=None):
    """org -> {org: [names], state: name, station: {term: [job_ids]}, county: {term: [job_ids]}}."""
    rows = conn.execute("SELECT org_id, kind, term, job_ids FROM news_lexicon" + (" WHERE org_id = ANY(%s)" if org_ids else ""),
                        ([list(org_ids)] if org_ids else ())).fetchall()
    out = {}
    for r in rows:
        o = out.setdefault(r["org_id"], {"org": [], "state": None, "station": {}, "county": {}})
        if r["kind"] == "org":
            o["org"].append(r["term"])
        elif r["kind"] == "state":
            o["state"] = r["term"]
        else:
            o[r["kind"]][r["term"]] = r["job_ids"] or []
    return out
