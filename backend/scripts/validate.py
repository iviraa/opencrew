import openpyxl
from rapidfuzz import fuzz, process

from app.config import MILE_M
from app.db import ROOT, connect


def sheet(name):
    wb = openpyxl.load_workbook(ROOT / "data/raw/organizer_overlaps.xlsx", read_only=True)
    rows = list(wb[name].iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:] if r[0]]


def main():
    with connect() as conn:
        jobs = conn.execute("SELECT id, org_id, name FROM job WHERE horizon = 'long'").fetchall()
        opps = {(o["job_a"], o["job_b"]): o for o in conn.execute("SELECT * FROM opportunity WHERE horizon = 'long'").fetchall()}
    names = {j["id"]: j["name"] for j in jobs}
    ids = {}
    for p in sheet("projects"):
        org = "desc" if p["project_id"].startswith("DESC") else "gpc"
        pool = {j["id"]: j["name"] for j in jobs if j["org_id"] == org}
        hit = process.extractOne(p["project_name"], pool, scorer=fuzz.token_sort_ratio)
        ids[p["project_id"]] = hit[2] if hit and hit[1] >= 80 else None
    passed = 0
    rows = sheet("overlaps")
    print(f"{'overlap':8} {'pair':56} {'their mi':>8} {'our mi':>7} {'gap d':>6} {'our gap':>7} tier")
    for o in rows:
        a, b = ids.get(o["project_id_a"]), ids.get(o["project_id_b"])
        opp = opps.get(tuple(sorted((a, b)))) if a and b else None
        pair = f"{(names.get(a) or '?')[:26]} / {(names.get(b) or '?')[:26]}"
        if opp:
            passed += 1
            print(f"{o['overlap_id']:8} {pair:56} {o['distance_mi']:8.2f} {opp['center_distance_m'] / MILE_M:7.2f} {o['time_gap (day)']:6} {opp['time_gap_days']:7} {opp['tier']}")
        else:
            print(f"{o['overlap_id']:8} {pair:56} {o['distance_mi']:8.2f}  MISSING")
    print(f"\n{passed}/{len(rows)} organizer overlaps found; {len(opps)} opportunities total from {len(jobs)} placed jobs")


if __name__ == "__main__":
    main()
