from app.llm import unsourced


def test_sourced_forms_pass():
    src = '{"id": 31, "closest_mi": 2.95, "pct": 83, "savings_usd": "$200,000 to $550,000", "in_service": "Jun 01, 2026", "total": 1234000}'
    assert unsourced("Opportunity #31 is 3.0 mi apart with 83% overlap, saving $200k to $550k.", src) == []
    assert unsourced("In service June 1, 2026.", src) == []
    assert unsourced("That is about $1.2M.", src) == []


def test_list_markers_are_not_numbers():
    assert unsourced("1. Jasper\n2. Okatie", "") == []


def test_invented_numbers_are_caught():
    src = '{"id": 31, "savings_usd": "$200,000 to $550,000"}'
    assert unsourced("It needs 12 crews and saves $5M.", src) == ["$5M", "12"]
    assert unsourced("Opportunity #32", src) == ["32"]


def test_percent_of_a_fraction_and_user_numbers():
    assert unsourced("overlap 83%", '{"time_overlap": 0.83}') == []
    assert unsourced("your 2 month limit", "limit me to 2 months") == []


def test_prose_check_rejects_any_number():
    assert unsourced("Both teams could meet in 2 weeks.", "") == ["2"]
