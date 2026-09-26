from datetime import date

from app.ingest.national import aps, bpa, idahopower, nvenergy, pacificorp, pge_ltp, pse
from app.ingest.national.west_common import month_year, text_stations, title_ends


def test_title_ends_reads_stations_out_of_project_names():
    assert title_ends("Borden-Storey 230 kV 1 and 2 Line Reconductoring") == ["Borden", "Storey"]
    assert title_ends("Estrella Substation Project") == ["Estrella"]
    assert title_ends("Gateway West 500kV Line – Hemingway to Mayfield") == ["Hemingway", "Mayfield"]
    assert title_ends("Camp Williams 345-138 KV Transformer And 138 KV Yard Addition") == ["Camp Williams"]
    assert title_ends("Project Quasar – 138kV Switching Station") == ["Quasar"]
    assert title_ends("Convert Bannock Creek from 46kV to 138kV") == ["Bannock Creek"]
    assert title_ends("Sedro Woolley – Bellingham #4 115 kV Rebuild") == ["Sedro Woolley", "Bellingham"]


def test_text_stations_and_dates():
    assert text_stations("folding at the Lantern 345 kV substation near the Hilltop substation") == ["Lantern", "Hilltop"]
    assert month_year("ISD is June 30, 2028 and phase 2 in 12/2029") == [date(2028, 6, 1), date(2029, 12, 1)]


def test_pge_table_joins_wrapped_names():
    text = """                     Project Name                                    Project Completion Date

                  Boring 57kV rebuild                                        June 2026

   Evergreen-Harborton 230kV and Harborton-St                                April 2029
            Marys 230kV Reconductor
Boring 57kV substation Rebuild Project
Justification: Old gear.
"""
    assert pge_ltp.table(text) == [["Boring 57kV rebuild", date(2026, 6, 1), None],
                                   ["Evergreen-Harborton 230kV and Harborton-St Marys 230kV Reconductor", date(2029, 4, 1), None]]


def test_pse_blocks_keep_dates_and_skip_completed():
    text = """                      Recently Completed Projects – Northern Region
   1. Old Line
        Estimated Date of Operation: 2024
                      Identified Needs and Planned Projects – Northern Region
   1. Lynden Substation Rebuild
       Need Date: 2026
       Estimated Date of Operation: 2027
Lynden serves 15,700 customers in Whatcom County.
"""
    b = pse.blocks(text)
    assert [(x["title"], x["year"], x["need"]) for x in b] == [("Lynden Substation Rebuild", 2027, "2026")]


def test_idaho_rows_go_to_the_nearest_anchor():
    text = """Table B-1
Region             Time Frame      Project Title                                     Project Scope
                                                                                     Build a new 500kV line from Boardman,
NorthernGrid       5 year          Boardman – Hemingway 500kV Line                   Oregon area to Hemingway
                                                                                     substation.
Treasure Valley    5 year          Build Shellrock station                           Build new Shellrock 138kV station.
Table B-2
"""
    rows = idahopower.table_b1(text)
    assert [r["title"] for r in rows] == ["Boardman – Hemingway 500kV Line", "Build Shellrock station"]
    assert rows[0]["scope"] == "Build a new 500kV line from Boardman, Oregon area to Hemingway substation."


def test_nv_entries_take_the_latest_date():
    text = """NV Energy North

Hilltop Phase Shifter Move
A new phase shifter at the Hilltop 345 kV substation. The projected ISD is June 2027.

Redwood Expansion
Phase-1 was energized in November 2024, ultimate addition of 140 MW in 2027.
"""
    e = nvenergy.entries(text)
    assert [x["title"] for x in e] == ["Hilltop Phase Shifter Move", "Redwood Expansion"]
    assert nvenergy.isd(" ".join(e[1]["text"])) == date(2027, 12, 1)


def test_aps_station_cleanup():
    assert aps.station("_I Ocotillo substation") == "Ocotillo"
    assert aps.station("Outer Circle substation (in-service 2027)") == "Outer Circle"
    assert aps.station("Point of Change of Ownership") is None
    assert aps.station("Four Comers substation") == "Four Corners"


def test_pacificorp_blocks_read_status_dates():
    text = """APPENDIX 2 – PACIFICORP EAST PROJECT LIST

HARVEST 138 KV SUBSTATION
Project Description
A. Participants: PacifiCorp
B. Status: Preliminary planning. Planned completion date 11/15/2027
C. Facilities: Construct a new 138 kV substation.
APPENDIX 3 – PACIFICORP WEST PROJECT LIST
"""
    b = pacificorp.blocks(text)
    assert b[0]["title"] == "HARVEST 138 KV SUBSTATION" and "11/15/2027" in b[0]["fields"]["status"]


def test_bpa_plans_parse_bullets():
    text = """  8.7.2     Northwest Montana Area
  Proposed Plans of Service
        Conkelley Substation Retirement
           • Description: Loop the Libby-Conkelley 230 kV line into Flathead substation.
           • Estimated Costs: $32,000,000
           • Expected Energization: 2027
  Recently Completed Plans of Service
  8.7.3     Spokane Area
"""
    p = bpa.plans(text)
    assert p == [{"title": "Conkelley Substation Retirement", "Description": "Loop the Libby-Conkelley 230 kV line into Flathead substation.",
                  "Estimated Costs": "$32,000,000", "Expected Energization": "2027"}]
