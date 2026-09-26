"""NYISO 2026 Gold Book Table VII (Proposed Transmission Facilities), read from the pdftotext -layout text."""
import hashlib
import json
import re
from datetime import date

from app.db import ROOT
from app.ingest.national.common import clear, register_org, register_source, save

TEXT = "data/raw/national/nyiso-goldbook/gb.txt"
PDF = "data/raw/national/nyiso-goldbook/2026-Gold-Book-Public.pdf"
TABLE = (7099, 7720)  # Table VII lines in gb.txt
OWNER = "NGRID"
SEASON = re.compile(r"\s{2,}(S|W|In-Service)\s{2,}(20\d\d)\s{2,}")
MONTH = {"S": 6, "W": 12}  # summer and winter capability periods
RATING = re.compile(r"^(N/A|-+|\d+(?:\.\d+)?\s?(?:MVA|MW)?)$", re.I)


def split(s):
    return [t for t in re.split(r"\s{2,}", s.strip()) if t]


def parse_row(line):
    """One Table VII data line -> dict, or None when the line is not a facility row."""
    m = SEASON.search(line)
    if not m:
        return None
    head, tail = split(line[:m.start()]), split(line[m.end():])
    owners = [i for i, t in enumerate(head) if re.fullmatch(r"[A-Za-z&]+(?:/[A-Za-z&]+)*", t) and t.isupper() and i < len(head) - 2]
    if not owners or len(tail) < 2:
        return None
    i = owners[0]
    queue = " ".join(head[:i]) or None
    owner, a, b = head[i], head[i + 1], head[i + 2]
    size = head[i + 3] if len(head) > i + 3 else None
    op, design = tail[0], tail[1]
    ratings, rest = [], tail[2:]
    while rest and len(ratings) < 3 and RATING.match(rest[0]):
        ratings.append(rest.pop(0))
    kvs = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", f"{op}/{design}")]
    miles = float(size) if size and re.fullmatch(r"-?\d+(?:\.\d+)?", size) else None
    return {"queue": queue, "owner": owner, "from": a, "to": b, "size": size, "miles": miles, "season": m.group(1), "year": int(m.group(2)),
            "kv_operating": op, "kv_design": design, "voltage_kv": int(max(kvs)) if kvs else None,
            "circuits": ratings[0] if ratings else None, "summer": ratings[1] if len(ratings) > 1 else None,
            "winter": ratings[2] if len(ratings) > 2 else None, "note": " ".join(rest) or None}


def facilities(lines):
    """Data rows with the free-text notes printed just above or below them."""
    rows, texts = [], {}
    for n, line in enumerate(lines):
        r = parse_row(line)
        if r:
            rows.append((n, r))
        elif line.strip() and len(line) - len(line.lstrip()) > 60 and "Projects (" not in line:
            texts[n] = line.strip()  # description wrapped onto its own line
    out = []
    for n, r in rows:
        near = [texts[k] for k in (n - 1, n + 1) if k in texts]
        out.append({**r, "notes": " ".join(x for x in [r["note"], *near] if x) or None})
    return out


def rows(lines):
    seen = {}
    for r in facilities(lines):
        if r["owner"] != OWNER or r["season"] == "In-Service":
            continue
        key = "|".join(str(r[k]) for k in ("owner", "from", "to", "kv_operating", "season", "year", "notes"))
        seen[key] = seen.get(key, 0) + 1
        ident = hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:10]  # stable for the same file
        same = r["from"] == r["to"]
        name = f"{r['from']} {r['voltage_kv'] or ''} kV".replace("  ", " ") if same else f"{r['from']} - {r['to']} {r['voltage_kv'] or ''} kV".replace("  ", " ")
        yield {
            "id": f"nyiso-{ident}", "name": f"{name} {r['size'].lower() if r['size'] and not r['miles'] and r['size'] != '-' else 'line' if not same else 'station work'}".strip(),
            "description": r["notes"], "voltage_kv": r["voltage_kv"], "in_service": date(r["year"], MONTH[r["season"]], 1), "start": None,
            "status": "proposed", "need": None, "length_mi": abs(r["miles"]) if r["miles"] else None, "cost_usd": None,
            "ends": [r["from"]] if same else [r["from"], r["to"]], "states": ["NY"], "counties": None,
            "source_project_id": f"NYISO queue {r['queue']}" if r["queue"] else "NYISO Gold Book Table VII", "planner": "NYISO", "state": "NY",
            "raw": r,
        }


def load(conn, manifest="data/raw/national/manifest_east.json"):
    lines = (ROOT / TEXT).read_text().splitlines()[TABLE[0] - 1:TABLE[1]]
    m = next(x for x in json.loads((ROOT / manifest).read_text()) if x["state"] == "NY")
    org = m["slug"]
    register_org(conn, org, m["utility"], "National Grid NY", "NY", "NYISO", org)
    clear(conn, org)
    doc = register_source(conn, org, "NYISO 2026 Gold Book, Table VII Proposed Transmission Facilities", m["url"], PDF, "NYISO", "2026 Gold Book")
    counts = {"placed": 0, "review": 0}
    for p in rows(lines):
        counts[save(conn, {**p, "org_id": org}, doc)] += 1
    print("NY", org, counts, flush=True)
    return {"NY": {"org": org, **counts}}
