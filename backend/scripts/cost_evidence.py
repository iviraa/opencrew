import re
from statistics import median

from app.config import ASSUMPTIONS, SOURCES
from app.db import ROOT
from app.ingest import desc, pdf

MILES = re.compile(r"(\d+(?:\.\d+)?)\s*(?:miles|mi\b)", re.I)


def desc_costs():
    rows, _ = desc.parse(pdf.read_pages(ROOT / "data/raw/desc_2024_2028_projects.pdf"))
    per_mile = {}
    for r in rows:
        m = MILES.search(f"{r['name']} {r['description'] or ''}")
        if m and r["job_type"] != "substation" and float(m.group(1)) >= 2:  # short taps skew $/mile
            per_mile.setdefault((r["job_type"], r["voltage_kv"]), []).append(r["cost_usd"] / float(m.group(1)))
    return rows, per_mile


def main():
    rows, per_mile = desc_costs()
    costs = [r["cost_usd"] for r in rows]
    print(f"DESC filing: {len(rows)} projects, median ${median(costs) / 1e6:.1f}M, range ${min(costs) / 1e6:.1f}M to ${max(costs) / 1e6:.1f}M")
    for (kind, kv), vals in sorted(per_mile.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
        print(f"  {kind:13} {kv or '':>4} kV: median ${median(vals) / 1e6:.2f}M per mile over {len(vals)} projects")
    mob = ASSUMPTIONS["mobilization_usd"]
    print(f"MISO mobilization ${mob['low']:,}-${mob['high']:,} is {100 * mob['low'] / median(costs):.1f}-{100 * mob['high'] / median(costs):.1f}% "
          "of the median DESC project")
    print("\nSources:")
    for key, s in SOURCES.items():
        have = "local copy" if s["file"] and (ROOT / s["file"]).exists() else ("web only" if not s["file"] else "MISSING local copy")
        print(f"  {key:17} {have:17} {s['title']}")
    print("\nAssumptions:")
    for key, a in ASSUMPTIONS.items():
        print(f"  {key:18} {a['low']:>9,} to {a['high']:>9,} {a['unit']:12} {'verified' if a['verified'] else 'estimate':9} p.{a['page']}")


if __name__ == "__main__":
    main()
