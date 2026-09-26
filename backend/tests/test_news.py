"""Utility-first news: lexicon terms, rule classification, linking, dedupe and the feed contract, all offline."""
from datetime import datetime, timezone

import pytest

from app.news import classify, feed, lexicon

LX = {
    "gpc": {"org": ["Georgia Power", "Southern Company"], "state": "Georgia", "station": {"Norcross": ["gpc-1"], "Goshen": ["gpc-9"]},
            "county": {"Gwinnett": ["gpc-2"]}},
    "desc": {"org": ["Dominion Energy", "SCE&G"], "state": "South Carolina", "station": {"Okatie": ["desc-1"]}, "county": {"Jasper": ["desc-1"]}},
}


def art(title, description="", published=None, url=None):
    return {"url": url or f"https://example.com/{abs(hash(title))}", "title": title, "description": description, "source": "Example",
            "published": published or datetime(2026, 9, 1, tzinfo=timezone.utc), "provider": "google_news", "query": "x"}


def test_station_terms_drop_voltages_work_words_and_generic_names():
    assert lexicon.station_term("Okatie 230 kV Substation") == "Okatie"
    assert lexicon.station_term("GAINESVILLE #2 EQUIPMENT REPLACEMENT") == "GAINESVILLE"
    assert lexicon.station_term("Church") is None
    assert lexicon.station_term("North") is None
    assert lexicon.station_term("Possum Branch") == "Possum Branch"


@pytest.mark.parametrize("text,impact", [
    ("Crews battle fire at substation", "damage"),
    ("Thousands without power after storm", "outage"),
    ("Residents oppose new 500 kV line route", "opposition"),
    ("Project delayed a year, utility says", "delay"),
    ("PSC approves rate case for transmission upgrades", "regulatory"),
    ("Transformer shortage stretches lead times to three years", "supply_chain"),
    ("Gunfire damages equipment at substation", "security"),
    ("DOE grant funds new interconnection", "funding"),
    ("Utility breaks ground on new line", "construction"),
    ("Company names new board member", "other"),
])
def test_rules_pick_the_impact(text, impact):
    assert classify.impact_of(text)[0] == impact


def test_link_needs_the_utility_and_ties_stations_and_counties_to_projects():
    a = art("Crews battle intense fire at Georgia Power substation in Norcross", "A fire in Gwinnett County, Georgia cut power to 3,000 customers.")
    got = classify.classify(a, LX, allow_llm=False)
    assert got["org_ids"] == ["gpc"] and set(got["job_ids"]) == {"gpc-1", "gpc-2"}
    assert got["impact"] == "damage" and got["affects_work"] is True and got["classified_by"] == "rules"
    assert got["evidence"]["station"] == ["Norcross"] and got["evidence"]["county"] == ["Gwinnett"]
    assert got["summary"].startswith("A fire in Gwinnett County")
    assert 0.5 < got["confidence"] <= 0.95


def test_county_alone_does_not_link_without_its_state():
    got = classify.classify(art("Georgia Power outage hits Jasper County"), LX, allow_llm=False)
    assert got["job_ids"] == []  # Jasper is a desc county, and Dominion is not named


def test_unrelated_story_is_dropped():
    assert classify.classify(art("City council debates parking", "Nothing about utilities."), LX, allow_llm=False) is None


def test_two_neighbors_in_one_story_link_both():
    got = classify.classify(art("Georgia Power and Dominion Energy plan joint rebuild near Okatie"), LX, allow_llm=False)
    assert got["org_ids"] == ["desc", "gpc"] and got["job_ids"] == ["desc-1"]


def test_dedupe_by_url_and_near_identical_headline():
    a = art("Storm knocks out power to 20,000 in Savannah", url="https://a.example/1")
    b = art("Storm knocks out power to 20,000 in Savannah", url="https://b.example/2")
    c = art("Storm knocks out power to 20,000 in Savannah", url="https://a.example/1")
    d = art("PSC approves new substation", url="https://c.example/3")
    assert len(feed.dedupe([a, b, c, d])) == 2


def test_summary_stays_within_the_story_and_200_chars():
    long = "First sentence here. " + "The outage " + "x" * 300 + " ended."
    s = classify.summary_of({"title": "t", "text": long}, "outage")
    assert s.startswith("The outage") and len(s) <= 200


def test_feed_item_shape_matches_the_contract():
    row = {"id": 1, "title": "t", "source": "s", "url": "u", "published": datetime(2026, 9, 1, tzinfo=timezone.utc), "impact": "delay",
           "affects_work": True, "summary": "sum", "confidence": 0.7, "org_ids": ["gpc"], "job_ids": ["gpc-1"], "opportunity_ids": [18],
           "verified": False, "evidence": {"org": ["Georgia Power"]}, "classified_by": "rules"}
    it = feed._item(row)
    assert set(it) == {"id", "title", "source", "url", "published", "impact", "affects_work", "summary", "confidence", "org_ids", "job_ids",
                       "opportunity_ids", "verified", "evidence"}
    assert it["published"] == "2026-09-01T00:00:00+00:00" and it["impact"] in classify.IMPACTS

