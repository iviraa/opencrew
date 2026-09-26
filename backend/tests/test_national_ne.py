from app.ingest.national import isone, nyiso


def test_isone_between_two_substations():
    t = "Install a new 115 kV ring bus substation on NEP’s R-144N line, between NEP’s Millbury Substation and RIE’s Woonsocket Substation"
    assert isone.stations(t) == ["Millbury", "Woonsocket"]


def test_isone_line_in_parentheses_and_dashes():
    assert isone.stations("Reconductor the K43 (New Haven - Williston) 115 kV line") == ["New Haven", "Williston"]
    assert isone.stations("T-172N Woonsocket-Hartford Ave-West Farnum 115 kV Line Reconductoring") == ["Woonsocket", "West Farnum"]
    assert isone.stations("Lines 1670 & 1771 Southington to Berlin Rebuild Project") == ["Southington", "Berlin"]


def test_isone_single_station_and_new_station_town():
    assert isone.stations("Stony Hill 48C 115 kV Substation Relay Upgrades") == ["Stony Hill"]
    assert isone.stations("Replace six 115 kV circuit breakers at Barnstable substation") == ["Barnstable"]
    assert isone.stations("Construct new 115 kV Switching Station in North Kingstown") == ["North Kingstown"]
    assert isone.stations("New Hampshire Asset Condition Structure Replacements - Line M127") == []
    assert isone.kv("Convert the planned 115 kV Mid-Cape line to 345 kV") == 345


def test_goldbook_line_row():
    line = ("                    NGRID                  Indian River                         North Watertown                          8.6"
            "              S        2026    115        115          1       3036       3280     New 8.6 mile 115kV circuit with 795ACSR")
    r = nyiso.parse_row(line)
    assert (r["owner"], r["from"], r["to"], r["miles"], r["season"], r["year"], r["voltage_kv"]) == ("NGRID", "Indian River", "North Watertown", 8.6, "S", 2026, 115)
    assert r["circuits"] == "1" and r["summer"] == "3036" and r["note"].startswith("New 8.6 mile")


def test_goldbook_station_row_and_queue():
    line = ("     1125                    NGRID                             Edic                                  Edic                 Substation"
            "            W        2026      345               345     N/A       N/A       N/A                                  SPCP: Terminal Upgrades")
    r = nyiso.parse_row(line)
    assert r["queue"] == "1125" and r["from"] == r["to"] == "Edic" and r["size"] == "Substation" and r["miles"] is None
    rows = list(nyiso.rows([line]))
    assert rows[0]["ends"] == ["Edic"] and rows[0]["in_service"].month == 12 and rows[0]["id"].startswith("nyiso-")
    assert nyiso.parse_row("     TIP Projects (19) (included in FERC 715 Base Case)") is None
