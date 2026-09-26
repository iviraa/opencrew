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

ACRE_M2 = 4046.86

ASSUMPTIONS = {
    "row_width_m": {"low": 30, "high": 45, "unit": "m", "label": "ROW width", "source": "typical 115-230 kV corridor", "verified": False},
    "land_usd_per_acre": {"low": 4000, "high": 7000, "unit": "$/acre", "label": "Land value", "source": "https://www.nass.usda.gov/Publications/Todays_Reports/", "verified": False},
    "yard_usd": {"low": 150000, "high": 400000, "unit": "$", "label": "Staging yard", "source": "placeholder", "verified": False},
    "mobilization_usd": {"low": 50000, "high": 150000, "unit": "$", "label": "Crew mobilization", "source": "placeholder", "verified": False},
    "outage_usd": {"low": 25000, "high": 100000, "unit": "$", "label": "Coordinated outage", "source": "placeholder", "verified": False},
}
