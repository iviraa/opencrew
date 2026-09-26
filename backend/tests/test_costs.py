from app.config import ASSUMPTIONS, MOB_SHARE, SOURCES, mob_share
from app.engine.plan import BURSTS, DEFAULTS


def test_every_assumption_is_cited():
    for key, a in ASSUMPTIONS.items():
        assert a["low"] <= a["high"], key  # always a range
        assert a["source"] and a["page"] and a["note"], key
        assert a["url"] and a["url"].startswith("https://"), key
        assert isinstance(a["verified"], bool), key


def test_sources_listed():
    titles = {s["title"] for s in SOURCES.values()}
    assert all(a["source"] in titles for a in ASSUMPTIONS.values())


def test_plan_costs_come_from_the_sourced_mobilization():
    assert abs(sum(MOB_SHARE.values()) - 1) < 1e-9  # the split covers one whole project mobilization
    m = ASSUMPTIONS["mobilization_usd"]
    total_low = sum(mob_share(k)[0] for k in MOB_SHARE) * 1000
    assert abs(total_low - m["low"]) <= 5 * 1000  # rounding only
    for key, b in BURSTS.items():
        assert (b["mob_low_k"], b["mob_high_k"]) == mob_share(key)
    yard = ASSUMPTIONS["yard_usd"]
    assert yard["low"] / 1000 <= DEFAULTS["costs"]["yard_k"] <= yard["high"] / 1000
