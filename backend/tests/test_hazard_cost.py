"""Cost of exposure and coordination savings, all offline on synthetic exposures."""
from datetime import date

from app.config import ASSUMPTIONS, PHASES, STOP_RULES
from app.hazards import cost


def exp(period="month", start="2026-08-01", end="2026-08-31", **days):
    hz = [{"hazard": h, "label": h, "why": "", "affected_days": {"forecast": int(d[0]) if period == "now7" else 0, "low": d[0], "high": d[1]}, "leans": [], "live": []}
          for h, d in days.items()]
    return {"kind": "site", "id": "x", "names": ["Site X"], "partners": [], "period": period, "start": start, "end": end, "days": 31, "counties": 2,
            "hazards": hz, "affected_days": {"forecast": 0, "low": 0, "high": 0}, "method": ""}


WINDOW = (date(2026, 1, 1), date(2027, 12, 31))


def test_crew_figures_are_cited_and_rules_have_documents():
    crew = {k: a for k, a in ASSUMPTIONS.items() if a.get("scope") == "crew"}
    assert {"crew_day_usd", "crane_standby_usd_day", "demob_remob_usd", "storm_rate_multiplier"} <= set(crew)
    assert all(a["low"] <= a["high"] and a["url"].startswith("https://") and a["note"] for a in crew.values())
    assert not ASSUMPTIONS["demob_remob_usd"]["verified"]  # modeled, never claimed as published
    assert all(r["source"] and r["url"] for r in STOP_RULES.values())


def test_phase_mix_follows_the_build_window():
    mix, inside = cost.phase_mix(WINDOW, date(2026, 1, 1), date(2026, 3, 31))
    assert inside and mix == {"survey & permitting": 1.0}  # the first 20% of a two-year window is all permitting
    mix, inside = cost.phase_mix(WINDOW, date(2027, 6, 1), date(2027, 6, 30))
    assert inside and "construction" in mix
    mix, inside = cost.phase_mix(WINDOW, date(2030, 6, 1), date(2030, 6, 30))
    assert not inside and abs(sum(mix.values()) - 1) < 1e-6 and mix == dict(PHASES)


def test_an_affected_day_costs_the_idle_crew_plus_the_phase_equipment():
    d = cost.per_day({"construction": 1.0}, "low")
    assert d["crew"] == round(ASSUMPTIONS["crew_day_usd"]["low"])
    assert d["equipment"] == round(sum(ASSUMPTIONS[k]["low"] for k in cost.EQUIPMENT["construction"]))
    assert cost.per_day({"survey & permitting": 1.0}, "high")["equipment"] == 0


def test_demob_is_picked_only_when_it_beats_standby_for_the_event():
    item = cost.hazard_item("tropical", {"low": 1, "high": 3}, {"construction": 1.0})
    assert item["option"]["high"] == "demob"  # three idle days of a full construction crew cost more than a move
    assert item["premium"]["high"] > 0 and item["rules"] == ["adverse_weather_structures"]
    wind = cost.hazard_item("wind", {"low": 1, "high": 1}, {"clearing": 1.0})
    assert wind["option"] == {"low": "standby", "high": "standby"}  # a one-day event is never worth a round trip
    assert wind["premium"] == {"low": 0, "high": 0} and wind["total"]["low"] <= wind["total"]["high"]


def test_site_cost_sums_hazards_and_lists_its_assumptions():
    c = cost.site_cost(exp(wind=(0.7, 1.5), flood=(0.1, 1.0), quiet=(0, 0)) | {"hazards": exp(wind=(0.7, 1.5), flood=(0.1, 1.0))["hazards"]}, WINDOW)
    assert [i["hazard"] for i in c["items"]] == ["wind", "flood"] and c["total"]["low"] <= c["total"]["high"]
    assert c["total"]["high"] == round(sum(i["total"]["high"] for i in c["items"]), -2)
    assert "crew_day_usd" in c["assumptions"] and c["inside_window"]


def test_now7_uses_the_forecast_count():
    c = cost.site_cost(exp("now7", "2026-09-26", "2026-10-03", storms=(2, 2)), WINDOW)
    assert c["items"][0]["days"] == {"low": 2.0, "high": 2.0}


def test_shared_days_never_exceed_the_smaller_site_and_shrink_with_the_commute():
    a, b = {"wind": {"high": 2.0}, "flood": {"high": 1.0}}, {"wind": {"high": 1.0}}
    near, far = cost.shared_days(a, b, 0, "high"), cost.shared_days(a, b, 40, "high")
    assert near == 1.0 and 0 < far < near
    assert cost.shared_days(a, b, 60, "high") == 0  # beyond a 45 minute drive nothing is shared
