from datetime import date

import pandas as pd

from app.ingest.national import spp


def row(**kw):
    base = {"NTC ID": 210001.0, "Project ID": 1, "Upgrade ID": 11, "Project Owner": "OGE", "State(s)": "OK/",
            "Project Name": "Line - Hugo - Sunnyside 345 kV", "Upgrade Name": "Hugo - Sunnyside 345 kV Ckt 1 Rebuild (OKGE)",
            "Project Type": "Regional \nReliability", spp.ISD: pd.Timestamp("2027-06-01"), spp.NEED: pd.Timestamp("2026-06-01"),
            spp.NTC: pd.Timestamp("2025-01-15"), "Source Study": "2024 ITP", "Baseline Cost Estimate": 1e6, "Baseline Cost Estimate Year": 2024.0,
            "Baseline Cost Estimate with Escalation": 1.1e6, "Current Cost Estimate": 1.2e6, "Final Cost": None, "Project Status": "On Schedule < 4",
            "From Bus Number": None, "From Bus Name": None, "To Bus Number": None, "To Bus Name": None, "Project Description/ Comments": "Rebuild",
            "Voltages (kV)": "345", "Number of New": None, "Number of Rebuild/Reconductor": 12.5, "Number of Voltage Conversion": None}
    return pd.Series({**base, **kw})


def test_stations_from_titles():
    assert spp.stations("Hugo - Sunnyside 345 kV") == ["Hugo", "Sunnyside"]
    assert spp.stations("Neset to Tioga 230kV Rebuild (DISIS-2017-001) (BEPC)") == ["Neset", "Tioga"]
    assert spp.stations("Rhame 230 kV Substation GEN-2017-010 Interconnection (TOIF) (BEPC)") == ["Rhame"]
    assert spp.stations("GEN-2016-071 Interconnection Costs") == []
    assert spp.bus("CUSHING 69") == "CUSHING" and spp.bus("Hoskins 345k") == "Hoskins" and spp.bus("Sub") is None


def test_row_maps_every_field():
    p = spp.mapped(row(), "OK")
    assert p["id"] == "spp-11" and p["ends"] == ["Hugo", "Sunnyside"] and p["voltage_kv"] == 345
    assert p["in_service"] == date(2027, 6, 1) and p["start"] == date(2025, 1, 15) and p["need"] == "regional reliability"
    assert p["cost_usd"] == 1.2e6 and p["length_mi"] == 12.5 and p["states"] == ["OK"] and p["raw"]["in_service_from"] == "owner"


def test_need_date_fallback_bus_names_and_done_rows():
    p = spp.mapped(row(**{spp.ISD: None, "From Bus Name": "Cherry County 345 kV", "To Bus Name": "Holt County 345 kV"}), "OK")
    assert p["in_service"] == date(2026, 6, 1) and p["raw"]["in_service_from"] == "rto_need_date"
    assert p["ends"] == ["Cherry County", "Holt County"]
    assert spp.mapped(row(**{"Project Status": "Complete"}), "OK") is None
    assert spp.mapped(row(**{spp.ISD: pd.Timestamp("2023-05-01")}), "OK") is None
