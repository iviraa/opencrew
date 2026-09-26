"""Prints the evidence behind every savings figure: the filing it is sized against, the sources, the prices, the quantities
and a worked example per tier. See docs/cost-savings-model.md."""
import re
from statistics import median

from app.config import ASSUMPTIONS, DRIVERS, MOB_SPLIT, SOURCES, driver
from app.db import ROOT
from app.engine.cost import savings
from app.ingest import desc, pdf

MILES = re.compile(r"(\d+(?:\.\d+)?)\s*(?:miles|mi\b)", re.I)

EXAMPLES = [  # one representative pair per tier, so the printout shows what the model actually produces
    ("crew range, chained 60 days apart", dict(tier="crew", overlap_m=0, drive_min=35, time_overlap=0.0,
                                               pair={"kv": 115, "gap_days": 60, "shared_days": 0, "cost_usd": 5e6})),
    ("same site, 80% concurrent, 230 kV", dict(tier="site", overlap_m=0, drive_min=15, time_overlap=0.8,
                                               pair={"kv": 230, "gap_days": 0, "shared_days": 500, "cost_usd": 20e6})),
    ("crossing, concurrent, 1.9 mi side by side", dict(tier="crossing", overlap_m=3000, drive_min=5, time_overlap=1.0,
                                                       pair={"kv": 115, "gap_days": 0, "shared_days": 300, "cost_usd": 8e6})),
    ("same site but a 60 min drive apart", dict(tier="site", overlap_m=0, drive_min=60, time_overlap=1.0,
                                                pair={"kv": 115, "gap_days": 0, "shared_days": 300, "cost_usd": 8e6})),
]


def desc_costs():
    rows, _ = desc.parse(pdf.read_pages(ROOT / "data/raw/desc_2024_2028_projects.pdf"))
    per_mile = {}
    for r in rows:
        m = MILES.search(f"{r['name']} {r['description'] or ''}")
        if m and r["job_type"] != "substation" and float(m.group(1)) >= 2:  # short taps skew $/mile
            per_mile.setdefault((r["job_type"], r["voltage_kv"]), []).append(r["cost_usd"] / float(m.group(1)))
    return rows, per_mile


def filing():
    """The filing the mobilization figure is sized against; skipped when the source PDF is not in data/raw."""
    try:
        rows, per_mile = desc_costs()
    except FileNotFoundError:
        print("DESC filing: data/raw/desc_2024_2028_projects.pdf not present, skipping the per-project comparison")
        return
    costs = [r["cost_usd"] for r in rows]
    print(f"DESC filing: {len(rows)} projects, median ${median(costs) / 1e6:.1f}M, range ${min(costs) / 1e6:.1f}M to ${max(costs) / 1e6:.1f}M")
    for (kind, kv), vals in sorted(per_mile.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
        print(f"  {kind:13} {kv or '':>4} kV: median ${median(vals) / 1e6:.2f}M per mile over {len(vals)} projects")
    mob = ASSUMPTIONS["mobilization_usd"]
    print(f"MISO mobilization ${mob['low']:,}-${mob['high']:,} is {100 * mob['low'] / median(costs):.1f}-{100 * mob['high'] / median(costs):.1f}% "
          "of the median DESC project")


def reconcile():
    """The bottom-up check on MISO's single mobilization figure, the same one test_engine asserts."""
    mob = ASSUMPTIONS["mobilization_usd"]["low"]
    crew_hour = ASSUMPTIONS["lineworker_hourly_usd"]["low"] * ASSUMPTIONS["labor_burden_factor"]["low"] * driver("crew_size", "low")
    labor = driver("setup_crew_days", "low") * driver("shift_hours") * crew_hour
    haul = driver("crew_moves", "low") * ASSUMPTIONS["demob_remob_usd"]["low"]
    print(f"\nMobilization split of ${mob:,.0f} checked from the bottom up:")
    print(f"  labor   {MOB_SPLIT['labor']:.0%} = ${mob * MOB_SPLIT['labor']:>9,.0f}  vs {driver('setup_crew_days', 'low'):.0f} crew-days x "
          f"${crew_hour:,.0f}/crew-h = ${labor:>9,.0f}  ({labor / (mob * MOB_SPLIT['labor']):.2f}x)")
    print(f"  travel  {MOB_SPLIT['travel']:.0%} = ${mob * MOB_SPLIT['travel']:>9,.0f}  vs {driver('crew_moves', 'low'):.0f} crew moves x "
          f"${ASSUMPTIONS['demob_remob_usd']['low']:,.0f} = ${haul:>9,.0f}  ({haul / (mob * MOB_SPLIT['travel']):.2f}x)")


def worked_examples():
    for label, kw in EXAMPLES:
        s = savings(**kw)
        share = s["share_of_budget"]
        head = f"${s['low']:,.0f} to ${s['high']:,.0f}"
        print(f"\n{label}: {head}" + (f"  ({share['low']:.1%} to {share['high']:.1%} of the smaller budget)" if share and s["high"] else ""))
        for c in s["categories"]:
            print(f"  {c['label']:18} ${c['low']:>10,.0f} to ${c['high']:>10,.0f}")
        for ln in s["lines"]:
            print(f"    {ln['name']}")
            print(f"      {ln['qty']}{' · ' + ln['over'] if ln['over'] else ''}  |  {ln['basis']}")
        if not s["lines"]:
            print("  nothing shareable: past the 45 minute drive limit or the windows are years apart")


def main():
    filing()
    reconcile()
    print("\nSources:")
    for key, s in SOURCES.items():
        have = "local copy" if s["file"] and (ROOT / s["file"]).exists() else ("web only" if not s["file"] else "MISSING local copy")
        print(f"  {key:17} {have:17} {s['title']}")
    print("\nPrices (ASSUMPTIONS):")
    for key, a in ASSUMPTIONS.items():
        print(f"  {key:38} {a['low']:>9,} to {a['high']:>9,} {a['unit']:36} {'verified' if a['verified'] else 'derived':9} p.{a['page']}")
    print("\nQuantities (DRIVERS):")
    for key, v in DRIVERS.items():
        span = f"{v[0]:g} to {v[1]:g}" if isinstance(v, tuple) else f"{v:g}"
        print(f"  {key:22} {span}")
    print("\nWorked examples:")
    worked_examples()


if __name__ == "__main__":
    main()
