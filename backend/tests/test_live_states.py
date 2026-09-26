"""Live storm feeds cover every state a utility on crewly works in."""
from datetime import datetime, timezone
from app.storm import live


def test_live_states_come_from_the_org_table():
    class Conn:
        def execute(self, sql, *a):
            assert "FROM org" in sql

            class R:
                def fetchall(self):
                    return [{"state": "GA"}, {"state": "TX"}]
            return R()
    assert live.utility_states(Conn()) == ("GA", "TX")
    text = "Time,Location,County,State,Lat,Lon,Comments\n1300,Here,Dallas,TX,32.8,-96.8,x\n1300,There,Fulton,GA,33.7,-84.4,y\n1300,Far,Cook,IL,41.8,-87.6,z\n"
    now = datetime(2026, 9, 1, 18, tzinfo=timezone.utc)
    assert {r[3]["state"] for r in live.parse_spc(text, "wind", now, ("GA", "TX"))} == {"GA", "TX"}
    assert {r[3]["state"] for r in live.parse_spc(text, "wind", now)} == {"GA"}
