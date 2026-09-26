import json
import re

from app.db import ROOT, connect, init_schema
from app.storm import helene

OWNERS = {"desc": re.compile(r"dominion|sce&g|south carolina (electric|gas)", re.I), "gpc": re.compile(r"georgia power", re.I)}


def load_assets(conn):
    conn.execute("TRUNCATE asset")
    rows = []
    for s in json.loads((ROOT / "data/layers/osm_substations.json").read_text()):
        org = next((o for o, rx in OWNERS.items() if rx.search(s.get("operator") or "")), None)
        if org and s.get("power") == "substation":
            rows.append((s["osm"], org, s["name"], f"POINT({s['lon']} {s['lat']})"))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO asset VALUES (%s, %s, %s, ST_GeogFromText(%s)) ON CONFLICT DO NOTHING", rows)
    return len(rows)


def main():
    helene.RAW.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        init_schema(conn)
        print("assets", load_assets(conn))
        conn.execute("DELETE FROM storm_event")
        for source, gen in [("NHC", helene.track_events), ("NHC", helene.cone_events), ("NWS via IEM", helene.warning_events), ("SPC", helene.spc_events), ("NWS LSR via IEM", helene.lsr_events)]:
            rows = [(ts, kind, wkt, json.dumps({**payload, "source": source})) for ts, kind, wkt, payload in gen()]
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO storm_event (ts, kind, geom, payload, confidence, verified) VALUES (%s, %s, ST_GeogFromText(%s), %s, 1.0, TRUE)", rows)
            print(gen.__name__, len(rows))


if __name__ == "__main__":
    main()
