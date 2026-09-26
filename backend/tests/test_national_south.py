from datetime import date

from app.ingest.national import ctpc, ercot, fl_tysp, sertp
from app.ingest.national.south_names import ends_from_title, station


def test_station_cleanup():
    assert station("Richland Chambers 345 kV Switch") == "Richland Chambers"
    assert station("White Mule (fka Elmar)") == "White Mule"
    assert station("Pleasant Valley/Fisher Road") == "Pleasant Valley"
    assert station("Generator") is None


def test_ends_from_titles():
    assert ends_from_title("Durham–RTP 230 kV Line, Reconductor") == ["Durham", "RTP"]
    assert ends_from_title("Beulah 100 kV Line (Lookout-EnergyUnited Del 18), Upgrade") == ["Lookout", "EnergyUnited Del 18"]
    assert ends_from_title("GAINESVILLE #2 - BULL SHOALS 161 KV TRANSMISSION LINE, REBUILD") == ["GAINESVILLE #2", "BULL SHOALS"]
    assert ends_from_title("Holly Ridge North 115 kV Switching Station, Construct") == ["Holly Ridge North"]


def test_ercot_row_keeps_oncor_only_and_drops_contact():
    row = {ercot.COL["num"]: "99391B", ercot.COL["title"]: "Stanton East - Spraberry 69 kV Line", ercot.COL["from"]: "Stanton East",
           ercot.COL["to"]: "Spraberry 138 kV Switch", ercot.COL["status"]: "Planned", ercot.COL["owner"]: "ONCOR",
           ercot.COL["isd"]: "2027-03-01", ercot.COL["kv"]: 138, ercot.COL["new_mi"]: 2.5, ercot.COL["up_mi"]: 1,
           ercot.COL["county_a"]: "Midland", ercot.COL["county_b"]: "Martin", ercot.COL["tier"]: "Tier 3", "TSP/Company Contact": "someone@x.com"}
    p = ercot.mapped(row, "PlannedTPIT")
    assert p["id"] == "ercot-99391B" and p["ends"] == ["Stanton East", "Spraberry"] and p["counties"] == ["Midland", "Martin"]
    assert p["length_mi"] == 3.5 and p["in_service"] == date(2027, 3, 1) and "TSP/Company Contact" not in p["raw"]
    assert ercot.mapped({**row, ercot.COL["owner"]: "CNP"}, "x") is None


def test_ctpc_rows_join_wrapped_titles():
    lines = ["     Appendix C",
             "                   Jacksonville 230 kV, Upgrade CT Ratio for East",
             "    E190052        Line and Add Tie Breaker                                    DEP        Underway       6/1/2026         2.1         TPL",
             "    W220209        Lyle Creek Switching Station, Construct                     DEC        Underway       6/1/2026         74       New Loads"]
    rows = list(ctpc.parse(lines))
    assert rows[0]["name"] == "Jacksonville 230 kV, Upgrade CT Ratio for East Line and Add Tie Breaker" and rows[1]["study"] == "New Loads"
    p = ctpc.mapped(rows[0])
    assert p["cost_usd"] == 2.1e6 and p["status"] == "under construction" and p["need"].startswith("reliability")


def test_fpl_table_and_hookup():
    line = "               FPL              Sweatt 1/      Whidden          79            June/2026            230            1,195"
    m = fl_tysp.LINE.match(line)
    assert m and m["to"].strip() == "Sweatt" and m["frm"].strip() == "Whidden" and m["mi"] == "79"
    r = {"section": "III.E.30", "title": "Terrill Creek Battery Energy Storage System Center in Clay County",
         "text": "connect the Terrill Creek Center in Clay County in the 2 nd Quarter of 2027 is projected to be: "
                 "Extend the existing 34.5 kV bus at Terrill Substation to connect the BESS."}
    p = fl_tysp.mapped_hookup(r)
    assert p["in_service"] == date(2027, 6, 30) and p["counties"] == ["Clay"] and p["ends"] == ["Terrill"]


def test_sertp_blocks():
    lines = ["                       TVA Balancing Authority Area",
             "   In-Service   2028", "        Year:",
             "Project Name:   CORDOVA - YUM YUM 161 KV TRANSMISSION LINE, RECONDUCTOR",
             " Description:   Reconductor ~23.5 miles of the Cordova - Yum Yum 161 kV line.",
             "  Supporting    Additional thermal capacity is needed", "  Statement:    in the Memphis, TN area."]
    b = list(sertp.blocks(lines))[0]
    assert b["area"] == "TVA" and b["year"] == 2028 and b["support"].endswith("Memphis, TN area.")
    p = sertp.mapped(b, "tva", "TN", "test")
    assert p["ends"] == ["CORDOVA", "YUM YUM"] and p["length_mi"] == 23.5 and p["in_service"] == date(2028, 12, 1)
