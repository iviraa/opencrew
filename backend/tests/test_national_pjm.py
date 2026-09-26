from datetime import date

from app.ingest.national import pjm


def test_location_parser_splits_lines_and_drops_noise():
    assert pjm.ends("Union REA - Honda MT") == ["Union REA", "Honda MT"]
    assert pjm.ends("Weirton\xa0–\xa0\xa0Carnegie\xa0- Tidd") == ["Weirton", "Carnegie"]
    assert pjm.ends("Fostor to E Lima 345 kV line") == ["Fostor", "E Lima"]
    assert pjm.ends("Laurel,Sharptown") == ["Laurel", "Sharptown"]
    assert pjm.ends("Columbia 69 kV") == ["Columbia"]
    assert pjm.ends("Summer Shade - Green County 161kV") == ["Summer Shade", "Green County"]
    assert pjm.ends("AD2-088 TAP - Laurel 69 kV") == ["Laurel"]
    assert pjm.ends("P5 Substation: Location CEII") == []
    assert pjm.ends(None) == []


def test_row_maps_every_field():
    r = {"Upgrade Id": "b1570.3", "Description": "Reconductor Union REA - Honda MT 69 kV line", "Project Type": "Baseline",
         "Voltage": "138/69", "Cost Estimate": 2.5, "Transmission Owner": "AEP", "State": "OH", "Location": "Union REA - Honda MT",
         "Equipment": "Transmission Line", "Task": "Reconductor", "Status": "UC", "Driver": "Baseline Load Growth Deliverability & Reliability",
         "Projected In Service Date": "12/1/2025", "Revised In-Service Date": "6/1/2021", "Percent Complete": 85}
    p = pjm.row(r, "OH")
    assert p["id"] == "pjm-b1570.3" and p["voltage_kv"] == 138 and p["cost_usd"] == 2.5e6
    assert p["in_service"] == date(2025, 12, 1)  # a stale revision does not win over a later projection
    assert p["status"] == "under construction" and p["need"].startswith("baseline:")
    assert p["ends"] == ["Union REA", "Honda MT"] and p["raw"]["Percent Complete"] == 85


def test_row_without_dates_falls_back_or_goes_to_review():
    base = {"Upgrade Id": "s1", "Status": "EP", "Location": "Hatfield", "Voltage": None, "Cost Estimate": 0.0}
    assert pjm.row({**base, "Required Date": "6/1/2027"}, "WV")["in_service"] == date(2027, 6, 1)
    assert pjm.row(base, "WV")["in_service"] is None and pjm.row(base, "WV")["cost_usd"] is None
