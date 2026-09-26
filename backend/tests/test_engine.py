from datetime import date, datetime

from app.engine.cost import SHARE, savings
from app.engine.scoring import score, tier_for, time_overlap
from app.ingest.classify import endpoints, job_type, parse_date, voltage


def dt(y, m=1):
    return datetime(y, m, 1)


def test_tiers():
    assert tier_for(0, touches=True) == "crossing"
    assert tier_for(1599) == "land"
    assert tier_for(7999) == "site"
    assert tier_for(40000) == "crew"
    assert tier_for(41000) is None  # past 25 mi


def test_time_overlap_uses_shorter_window():
    assert time_overlap(dt(2024), dt(2026), dt(2025), dt(2025, 7)) == 1.0
    assert time_overlap(dt(2024), dt(2025), dt(2026), dt(2027)) == 0.0
    assert round(time_overlap(dt(2024), dt(2026), dt(2025), dt(2027)), 2) == 0.5


def test_score():
    assert score("crossing", 0.8) == 1.0
    assert score("crew", 0.0) == 0.3 * 0.2
    assert score("land", 0.3, risk=0.5) == 0.8 * 0.5 * 1.5


def test_savings_stack_and_range():
    crew, site = savings("crew", 0), savings("site", 0)
    assert crew["low"] < crew["high"]
    assert set(site["items"]) - set(crew["items"]) == {"One laydown yard instead of two"}  # a yard needs the sites within 5 mi
    land = savings("land", 2000)
    assert {"Width saved by sharing one corridor", "One route survey and environmental walk-down"} <= set(land["items"])
    assert savings("land", 0)["items"].keys() == site["items"].keys()  # no corridor, no land savings


def test_savings_overrides():
    s = savings("crew", 0, {"mobilization_usd": {"low": 10000, "high": 20000}})
    assert (s["low"], s["high"]) == (10000 * SHARE["low"], 20000)  # the mobilization split covers one whole mobilization


def test_savings_scale_per_pair():
    full = savings("crew", 0, drive_min=0, time_overlap=1.0, pair={"kv": 230, "gap_days": 0})
    half = savings("crew", 0, drive_min=0, time_overlap=0.5, pair={"kv": 230, "gap_days": 0})
    small = savings("crew", 0, drive_min=0, time_overlap=1.0, pair={"kv": 115, "gap_days": 0})
    commute = savings("crew", 0, drive_min=45, time_overlap=1.0, pair={"kv": 230, "gap_days": 0})
    assert half["high"] == full["high"] / 2 and small["high"] < full["high"] and commute["high"] < full["high"]
    assert savings("crew", 0, time_overlap=0.0, pair={"kv": 230, "gap_days": 90})["high"] > 0  # back-to-back crews can chain
    assert savings("crew", 0, time_overlap=0.0, pair={"kv": 230, "gap_days": 400})["high"] == 0  # years apart share nothing


def test_savings_lines_add_up_and_name_a_cost_type():
    from app.config import CATEGORY_LABEL
    s = savings("crossing", 3000, drive_min=5, time_overlap=1.0, pair={"kv": 230, "gap_days": 0, "shared_days": 300, "cost_usd": 9e6})
    for end in ("low", "high"):
        assert sum(ln[end] for ln in s["lines"]) == s[end]  # the table has to add up to the headline
        assert sum(c[end] for c in s["categories"]) == s[end]
    assert all(ln["category"] in CATEGORY_LABEL for ln in s["lines"])
    assert all(ln["qty"] and ln["basis"] for ln in s["lines"])  # every line says how many and where the price came from
    assert [c["high"] for c in s["categories"]] == sorted((c["high"] for c in s["categories"]), reverse=True)


def test_savings_recurring_lines_need_shared_days_and_a_budget():
    base = dict(tier="site", overlap_m=0, drive_min=10, time_overlap=0.8)
    bare = savings(**base, pair={"kv": 115, "gap_days": 0, "shared_days": 0, "cost_usd": None})
    timed = savings(**base, pair={"kv": 115, "gap_days": 0, "shared_days": 400, "cost_usd": None})
    budgeted = savings(**base, pair={"kv": 115, "gap_days": 0, "shared_days": 400, "cost_usd": 9e6})
    assert not any(ln["over"] for ln in bare["lines"])  # nothing runs with the calendar without shared days
    assert {"Per diem and lodging for one crew, not two", "Crane and stringing gear held once"} <= set(timed["items"])
    assert "time" not in {c["key"] for c in timed["categories"]} and "time" in {c["key"] for c in budgeted["categories"]}
    assert budgeted["share_of_budget"]["high"] < 0.15  # a coordination saving is a slice of the project, never most of it


def test_mobilization_split_reconciles_with_crew_and_move_rates():
    """MISO gives one mobilization figure; our split into hauling, crew and facilities has to survive a bottom-up check."""
    from app.config import ASSUMPTIONS as A, MOB_SPLIT, driver
    mob_low = A["mobilization_usd"]["low"]
    crew_hour = A["lineworker_hourly_usd"]["low"] * A["labor_burden_factor"]["low"] * driver("crew_size", "low")
    bottom_up_labor = driver("setup_crew_days", "low") * driver("shift_hours") * crew_hour
    assert 0.5 <= bottom_up_labor / (mob_low * MOB_SPLIT["labor"]) <= 2.0  # crew-days x loaded crew-hour lands within 2x of the split
    bottom_up_haul = driver("crew_moves", "low") * A["demob_remob_usd"]["low"]
    assert 0.5 <= bottom_up_haul / (mob_low * MOB_SPLIT["travel"]) <= 2.0  # crew moves x the per-move rate does too
    assert abs(sum(MOB_SPLIT.values()) - 1) < 1e-9


def test_name_parsing():
    assert endpoints("Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds") == ["Stevens Creek", "Hooks"]
    assert endpoints("SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD") == ["GOSHEN (SAV)", "MCINTOSH"]
    assert endpoints("Union Pier 115-13.8 kV Sub: Tap") == ["Union Pier"]
    assert voltage("Okatie 230-115kV Substation, Jasper – Yemassee 230kV #1 Fold-in") == 230
    assert job_type("Jasper – Okatie 230 kV #2: Construct") == "new_line"
    assert job_type("EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD") == "line_upgrade"
    assert job_type("SAV: MCINTOSH - PURRYSBURG 230KV REACTORS") == "substation"
    assert parse_date("12/31/2025 (phase 1) and 10/01/2026") == date(2026, 10, 1)


def test_flags():
    from app.engine.flags import flags, in_hurricane_season
    assert in_hurricane_season(dt(2025, 7), dt(2025, 8))
    assert not in_hurricane_season(dt(2025, 1), dt(2025, 3))
    a = {"name": "Hooks - Thurmond 115kV Tie: Rebuild", "endpoints": ["Hooks", "Thurmond"]}
    b = {"name": "EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD", "endpoints": ["EVANS PRIMARY", "THURMOND DAM (USA) #5"]}
    assert set(flags(a, b, 0.9, dt(2024), dt(2026), dt(2025), dt(2027))) == {"hurricane_season_high_risk", "tie_line", "shared_endpoint"}


def test_shared_wetland_flag():
    from app.engine.flags import flags
    from app.geo.wetlands import key
    a = {"name": "A - B 115kV Rebuild", "endpoints": ["A", "B"]}
    b = {"name": "C - D 230kV Rebuild", "endpoints": ["C", "D"]}
    args = (a, b, 0.0, dt(2024), dt(2025), dt(2024), dt(2025))
    assert "shared_wetland" in flags(*args, ({"17616269": "Riverine"}, {"17616269": "Riverine", "7207187": "Forested"}))
    assert "shared_wetland" not in flags(*args, ({"1": "Riverine"}, {"2": "Riverine"}))
    assert "shared_wetland" not in flags(*args, (None, {"2": "Riverine"}))  # service had no answer
    assert key({"type": "Point", "coordinates": [-81.15, 32.35]}) == key({"coordinates": [-81.15, 32.35], "type": "Point"})


def test_phase_share():
    from app.engine.scoring import phase_share
    assert phase_share(None, "construction") is None
    assert phase_share("construction", "clearing") == phase_share("clearing", "construction")
    assert phase_share("construction", "construction")[0] == 1.0
    assert phase_share("survey & permitting", "energization")[0] < 1.0
    assert "permits" in phase_share("survey & permitting", "survey & permitting")[1]


def test_phase_score_and_shareable():
    from app.queries import shareable
    assert score("site", 0.8, phase_factor=0.4) == 0.5 * 1.0 * 0.4
    assert shareable("crew") == ["crews", "equipment"]  # long horizon unchanged
    assert shareable("crew", "energization", "energization") == ["coordinated outage windows"]
    assert shareable("crossing", "survey & permitting", "construction") == ["schedule coordination", "outage timing", "crossing structures"]


def test_drive_time_rules():
    from app.engine.scoring import too_far
    from app.queries import shareable
    assert not too_far(None) and not too_far(45) and too_far(46)
    near, far = savings("site", 0, drive_min=30), savings("site", 0, drive_min=60)
    assert near["high"] > 0 and far["high"] == 0  # crews and yards need a 45 min drive
    assert "crews" not in shareable("crew", drive_min=60) and "crews" in shareable("crew", drive_min=20)
    assert score("site", 0.8, drive_min=60) == score("site", 0.8) * 0.5
