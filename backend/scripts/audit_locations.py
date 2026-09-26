import json
from collections import Counter

from app.db import ROOT, connect

OUT = ROOT / "data/layers/location_audit.json"


def main():
    with connect() as conn:  # the ingest pipeline audits each placement (app.geo.audit) and stores the verdict in located_via
        placed = conn.execute("""SELECT id, org_id, name, geom_quality AS quality, confidence, located_via AS via
                                 FROM job WHERE horizon = 'long' ORDER BY org_id, id""").fetchall()
        unplaced = conn.execute("""SELECT org_id, raw->>'id' AS id, raw->>'name' AS name, reason
                                   FROM job_review ORDER BY org_id, raw->>'id'""").fetchall()
    counts, by_org = Counter(), Counter()
    for r in placed:
        via = r["via"] or {}
        r["status"] = "ok" if r["quality"] == "manual" else via.get("audit", "unchecked")  # hand placements are trusted
        r["reasons"] = via.get("reasons", [])
        counts[r["status"]] += 1
        by_org[r["org_id"]] += 1
    OUT.write_text(json.dumps({"summary": {**counts, "placed": dict(by_org), "unplaced": len(unplaced)}, "placed": placed, "unplaced": unplaced},
                              indent=1, default=str))
    print(f"placed {len(placed)} {dict(by_org)}: {counts['ok']} ok, {counts['suspect']} suspect, {counts['wrong']} wrong")
    for r in placed:
        if r["status"] != "ok":
            print(f"  {r['status']:7} {r['id']:11} {r['name'][:50]:50} {'; '.join(r['reasons'])}")
    print(f"unplaced {len(unplaced)}:")
    for u in unplaced:
        print(f"  {u['id'] or '':11} {(u['name'] or '')[:50]:50} {u['reason']}")
    print("written", OUT)


if __name__ == "__main__":
    main()
