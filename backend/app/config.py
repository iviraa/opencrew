import json
from pathlib import Path

MILE_M = 1609.344
OVERLAP_RADIUS_M = 25 * MILE_M  # challenge rule: within 25 mi

TIERS = [("crossing", 0.0), ("land", 1600.0), ("site", 8000.0), ("crew", OVERLAP_RADIUS_M)]
TIER_WEIGHT = {"crossing": 1.0, "land": 0.8, "site": 0.5, "crew": 0.3}
SHAREABLE = {
    "crossing": ["outage timing", "crossing structures"],
    "land": ["right-of-way", "access roads", "permits"],
    "site": ["laydown yards", "deliveries"],
    "crew": ["crews", "equipment"],
}

DEFAULT_DURATION_MONTHS = {"new_line": 36, "line_upgrade": 18, "substation": 24}  # fallback when filing has no start

PHASES = [("survey & permitting", 0.20), ("clearing", 0.15), ("construction", 0.55), ("energization", 0.10)]

PHASE_SHARE = {  # sorted phase pair -> (score factor, what concurrent phases can share)
    ("clearing", "clearing"): (1.0, ["crews", "equipment", "staging yards"]),
    ("clearing", "construction"): (0.8, ["crews", "equipment", "staging yards"]),
    ("construction", "construction"): (1.0, ["crews", "cranes", "equipment", "staging yards"]),
    ("survey & permitting", "survey & permitting"): (1.0, ["right-of-way surveys", "permits", "environmental review"]),
    ("energization", "energization"): (1.0, ["coordinated outage windows"]),
}
PHASE_MISMATCH = (0.4, ["schedule coordination"])

MAX_DRIVE_MIN = 45  # a crew or yard serves both sites only within this road time
DRIVE_FACTOR = 0.5  # score penalty when the sites are farther apart by road
ROAD_BOUND = {"crews", "equipment", "cranes", "staging yards", "laydown yards", "deliveries"}

ACRE_M2 = 4046.86

SOURCES = json.loads((Path(__file__).parent / "cost_sources.json").read_text())
CREW = json.loads((Path(__file__).parent / "crew_costs.json").read_text())  # crew, equipment standby and storm-rate figures with their documents
SOURCES.update({k: {"title": v["title"], "url": v["url"], "file": f"data/raw/costs/crew/{v.get('file', '')}"} for k, v in CREW["sources"].items()})


def cite(key, page):
    return {"source": SOURCES[key]["title"], "url": SOURCES[key]["url"], "page": page}


# every range comes from a document; verified=False means derived or a proxy, and the note says how
ASSUMPTIONS = {
    "row_width_m": {"low": 27, "high": 38, "unit": "m", "label": "Right-of-way width", "verified": True, **cite("miso_2024", "32, table 3.1-1"),
                    "note": "115 kV lines use 90 ft (27 m) and 230 kV lines 125 ft (38 m)."},
    "land_usd_per_acre": {"low": 4500, "high": 15300, "unit": "$/acre", "label": "Land value", "verified": True, **cite("usda_2026", "15, pasture value by state"),
                          "note": "2026 pasture: SC $4,500 and GA $5,100 per acre. High end uses MISO's rule that cropland costs 3x pasture (MTEP24 guide p.8)."},
    "mobilization_usd": {"low": 100000, "high": 200000, "unit": "$", "label": "Crew mobilization", "verified": True, **cite("miso_2018", "16, section 4.1.1.3"),
                         "note": "Mobilizing and demobilizing all equipment and people for a line project: $100k at 115 kV, $200k at 230 kV (2018 dollars). "
                                 "That is about 1-2% of a typical DESC project in our filing (median near $10M)."},
    "yard_usd": {"low": 157590, "high": 262660, "unit": "$", "label": "Staging yard", "verified": False, **cite("miso_2018", "39, section 4.2.1.2"),
                 "note": "No public unit cost for temporary laydown yards. Proxy: MISO's site mobilization for an existing ($157,590) or new ($262,660) substation site."},
    "outage_usd": {"low": 28000, "high": 84000, "unit": "$", "label": "Coordinated outage", "verified": False, **cite("bls_ooh", "web page"),
                   "note": "Derived: one shared outage avoids 2 switching crews x 2 shifts x 10 hours at the storm crew-hour cost."},
    "per_diem_usd_day": {"low": 68, "high": 181, "unit": "$/person-day", "label": "Crew per diem", "verified": True, **cite("gsa_per_diem_2027", "FY2027 standard CONUS rate"),
                         "note": "Standard CONUS rate: $68 meals and incidentals, $113 lodging. Low end is a crew that sleeps at home and only claims M&IE; "
                                 "high end is the full $181 for a travelling crew."},
    "escalation_pct_yr": {"low": 3.2, "high": 5.12, "unit": "%/year", "label": "Construction escalation", "verified": False,
                          **cite("bls_eci_construction", "CIU2012300000000I Q2 2016 = 124.6 to Q2 2025 = 165.4; WPUIP2300001 Aug 2016 = 209.5 to Aug 2025 = 328.3"),
                          "note": "Nine-year compound growth from two BLS series: 3.20%/yr for construction total compensation (ECI) and 5.12%/yr for goods "
                                  "going into construction (PPI). Labour-heavy work sits near the low end, material-heavy work near the high end."},
    **{},  # crew figures are merged below so /api/assumptions and the cost UI show them with their sources
    "crew_hour_usd": {"low": 700, "high": 2100, "unit": "$/crew-hour", "label": "Storm crew hour", "verified": False, "scope": "storm",
                      **cite("gpc_helene_cost", "web page"),
                      "note": "Low: 5 line workers x $45.83 median wage (BLS, May 2025) x 1.5 storm overtime x 2 for trucks and overhead. "
                              "High: Georgia Power's $1.1B Helene restoration cost over 15,000+ workers for about 11 days at 16 hours, per 5-person crew "
                              "(workforce from Georgia Power's Sept 29, 2024 release)."},
}

# two crew figures have no public dollar value; they are modeled from the notes in crew_costs.json and stay verified=False
CREW_FILL = {"demob_remob_usd": (3100, 6200, "Modeled from the note's worked example: a 5-person crew with a bucket truck and a digger derrick, "
                                             "3 h (low) or 6 h (high) each way at loaded wages plus FEMA and Caltrans equipment rates, before per diem."),
             "mutual_aid_overhead_pct": (0, 15, "Public mutual-aid rules reimburse actual costs with no markup on expenses (0%); the only public "
                                                "markup found is Caltrans's 15% on equipment in force-account work, used as the high end.")}


def crew_assumption(key, a):
    lo, hi, note = a["low"], a["high"], a["note"]
    if lo is None or hi is None:
        lo, hi, note = CREW_FILL[key][0], CREW_FILL[key][1], CREW_FILL[key][2] + " " + note
    src = CREW["sources"][a["source_key"]]
    return {"low": lo, "high": hi, "unit": a["unit"], "label": a["label"], "verified": bool(a["verified"]) and lo == a["low"], "scope": "crew",
            "source": src["title"], "url": src["url"], "page": a["page_or_section"] or "derived", "note": note or a["page_or_section"]}


CREW_ASSUMPTIONS = {k: crew_assumption(k, a) for k, a in CREW["assumptions"].items()}
STOP_RULES = {k: {**r, "source": CREW["sources"][r["source_key"]]["title"], "url": CREW["sources"][r["source_key"]]["url"]}
              for k, r in CREW["stop_rules"].items()}  # thresholds that make a weather day an affected day, with their documents

ASSUMPTIONS.update(CREW_ASSUMPTIONS)

MOB_SHARE = {"general": 0.30, "heavy_haul": 0.15, "crane_lift": 0.20, "wire_stringing": 0.25, "commissioning": 0.10}  # our split of MISO's per-project mobilization

# ---------- savings model: what a duplicated setup is made of ----------
# ASSUMPTIONS hold prices; these hold quantities. A pair means (low, high); a number is fixed. docs/cost-savings-model.md shows the working.
DRIVERS = {
    "crew_size": (4, 6),                  # workers on a transmission line crew, the same range crew_day_usd is built on
    "shift_hours": 10,                    # a normal, non-storm field shift
    "crew_moves": (10, 18),               # crew-and-equipment round trips inside one project mobilization
    "setup_crew_days": (14, 20),          # crew-days spent standing a site up and tearing it down
    "survey_days_per_mile": (0.5, 1.5),   # crew-days of route survey and environmental walk-down per corridor mile
    "row_shared_frac": (0.3, 0.6),        # share of one line's right-of-way width that co-locating actually avoids buying twice
    "switch_crews": 2,                    # one crew at each end of a line to open it and close it again
    "switch_shifts": 2,                   # out of service and back in
    "gear_days": (10, 20),                # days a crane and a stringing set sit on one site per campaign
    "gear_share": (0.15, 0.35),           # share of those days a single shared set can cover both sites
    "crew_share": (0.10, 0.25),           # share of shared field days one crew genuinely covers both sites
    "months_pulled_in": (1, 3),           # months the second project stops waiting on the corridor and the outage
}

# MISO publishes one mobilization figure per project; this is our split of what it pays for, so the table can name the cost type
MOB_SPLIT = {"travel": 0.45, "labor": 0.35, "overhead": 0.20}

CATEGORIES = [  # the cost types the savings table groups by, in the order it shows them
    ("labor", "Labor", "Crew hours one side no longer has to pay for"),
    ("equipment", "Equipment", "Machines that would otherwise be hired or held twice"),
    ("travel", "Travel", "Hauling, lodging and per diem for a second crew"),
    ("time", "Time", "What the calendar costs: months of waiting and a second outage window"),
    ("land", "Land and permits", "Easements, surveys and environmental review bought once"),
    ("overhead", "Site and overhead", "A second yard's setup, rent and temporary facilities"),
]
CATEGORY_LABEL = {k: (label, hint) for k, label, hint in CATEGORIES}


def driver(key, end="low"):
    v = DRIVERS[key]
    return float(v[0 if end == "low" else 1]) if isinstance(v, tuple) else float(v)


def mob_share(key):
    m = ASSUMPTIONS["mobilization_usd"]
    return round(m["low"] * MOB_SHARE[key] / 1000), round(m["high"] * MOB_SHARE[key] / 1000)  # $k low and high

STATUSES = ["not_contacted", "drafted", "sent", "replied", "call_scheduled", "agreed", "declined"]
