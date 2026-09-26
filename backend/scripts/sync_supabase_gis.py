"""Copy the planner's GIS tables into Supabase (schema `planner`, PostGIS) over HTTPS: works on networks that block port 5432.

Needs SUPABASE_ACCESS_TOKEN (a personal access token) and SUPABASE_PROJECT_REF. Safe to rerun: each table is emptied and reloaded.
"""
import os
import re
import subprocess
import sys

import httpx

from app.db import ROOT

TABLES = ["org", "source_doc", "job", "job_version", "job_review", "opportunity", "contact", "outreach", "tract", "asset", "grid_line",
          "job_hazard", "storm_event", "incident", "outlook", "phase_risk", "joint_plan", "storm_plan",
          "hazard_fetch", "hazard_layer", "hazard_climate", "hazard_nri"]  # parents first; everything the app reads
CHUNK = 700_000  # bytes of sql per request


def run(sql):
    r = httpx.post(f"https://api.supabase.com/v1/projects/{os.environ['SUPABASE_PROJECT_REF']}/database/query", timeout=300,
                   headers={"Authorization": f"Bearer {os.environ['SUPABASE_ACCESS_TOKEN']}"}, json={"query": sql})
    if r.status_code >= 300:
        raise RuntimeError(f"{r.status_code}: {r.text[:500]}")
    return r.json()


def schema_sql():
    """The planner schema without timescaledb: hypertables become plain tables."""
    s = (ROOT / "backend/app/schema.sql").read_text()
    s = s.replace("CREATE EXTENSION IF NOT EXISTS postgis;", "").replace("CREATE EXTENSION IF NOT EXISTS timescaledb;", "")
    s = re.sub(r"SELECT create_hypertable\([^;]*\);", "", s)
    return ("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;\nCREATE SCHEMA IF NOT EXISTS planner;\n"
            "REVOKE ALL ON SCHEMA planner FROM anon, authenticated;\nSET search_path = planner, extensions;\n" + s)


SNAPSHOT = {"job_version": "", "storm_event": "", "incident": "", "outlook": "", "job": "ORDER BY parent_job_id IS NOT NULL"}  # hypertables and parents-before-phases need a plain, ordered copy


def table_ddl(table):
    """CREATE TABLE for a table defined outside schema.sql, taken from the local database."""
    out = subprocess.run(["pg_dump", "--schema-only", "--no-owner", "--no-privileges", "-t", f"public.{table}", os.environ["DATABASE_URL"]],
                         capture_output=True, text=True, check=True).stdout
    m = re.search(r"CREATE TABLE public\.\w+ \((?:.|\n)*?\n\);", out)
    return m.group(0).replace("CREATE TABLE public.", "CREATE TABLE IF NOT EXISTS planner.").replace("public.", "planner.") if m else ""


def dump(table):
    url, src = os.environ["DATABASE_URL"], table
    if table in SNAPSHOT:
        src = f"_sync_{table}"
        subprocess.run(["psql", url, "-qc", f"DROP TABLE IF EXISTS public.{src}; CREATE TABLE public.{src} AS SELECT * FROM public.{table} {SNAPSHOT[table]};"],
                       check=True)
    try:
        out = subprocess.run(["pg_dump", "--data-only", "--inserts", "--rows-per-insert=200", "--no-owner", "--no-privileges", "-t", f"public.{src}",
                              url], capture_output=True, text=True, check=True).stdout
    finally:
        if src != table:
            subprocess.run(["psql", url, "-qc", f"DROP TABLE IF EXISTS public.{src};"], check=True)
    stmts, cur = [], None
    for ln in out.splitlines():  # multi-row inserts span lines: keep whole statements
        if ln.startswith("INSERT INTO"):
            cur = [ln.replace(f"INSERT INTO public.{src}", f"INSERT INTO planner.{table}")]
        elif cur is not None:
            cur.append(ln)
        if cur is not None and ln.endswith(");"):
            stmts.append("\n".join(cur))
            cur = None
    return stmts


REFS = """
CREATE TABLE IF NOT EXISTS planner.state (fips TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL, geom geometry(MultiPolygon, 4326));
CREATE TABLE IF NOT EXISTS planner.county (geoid TEXT PRIMARY KEY, state TEXT NOT NULL, name TEXT NOT NULL, geom geometry(MultiPolygon, 4326));
CREATE TABLE IF NOT EXISTS planner.osm_station (osm TEXT PRIMARY KEY, state TEXT NOT NULL, name TEXT NOT NULL, operator TEXT, power TEXT, voltage TEXT,
                                                geom geometry(Point, 4326));
CREATE INDEX IF NOT EXISTS county_state_idx ON planner.county (state);
CREATE INDEX IF NOT EXISTS osm_station_state_idx ON planner.osm_station (state);
"""


def q(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def shapes(zip_path):
    import io
    import zipfile

    import shapefile
    from shapely.geometry import MultiPolygon, shape
    from shapely.wkt import dumps
    z = zipfile.ZipFile(ROOT / zip_path)
    base = next(n for n in z.namelist() if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), dbf=io.BytesIO(z.read(base + ".dbf")))
    for rec, shp in zip(r.records(), r.shapes()):
        g = shape(shp.__geo_interface__)
        yield rec, dumps(MultiPolygon([g]) if g.geom_type == "Polygon" else g, rounding_precision=5)


def batched(stmts, prefix="SET search_path = planner, extensions;\n"):
    batch = []
    for ln in stmts + [None]:
        if ln is None or sum(map(len, batch)) + len(ln) > CHUNK:
            if batch:
                run(prefix + "\n".join(batch))
            batch = []
        if ln is not None:
            batch.append(ln)


def reference_tables():
    """Boundaries and the substation reference every state was placed with, so loading can run from the cloud too."""
    import json
    run(REFS + "TRUNCATE planner.state, planner.county, planner.osm_station;")
    st = [f"INSERT INTO planner.state VALUES ({q(r['STATEFP'])}, {q(r['STUSPS'])}, {q(r['NAME'])}, ST_GeomFromText({q(w)}, 4326));"
          for r, w in shapes("data/layers/states.zip")]
    batched(st)
    co = [f"INSERT INTO planner.county VALUES ({q(r['GEOID'])}, {q(r['STUSPS'])}, {q(r['NAME'])}, ST_GeomFromText({q(w)}, 4326));"
          for r, w in shapes("data/layers/counties_20m.zip")]
    batched(co)
    osm = []
    for path in sorted((ROOT / "data/layers/osm_states").glob("*.json")):
        for x in json.loads(path.read_text()):
            if x.get("name"):
                osm.append(f"INSERT INTO planner.osm_station VALUES ({q(x['osm'])}, {q(path.stem)}, {q(x['name'])}, {q(x.get('operator'))}, "
                           f"{q(x.get('power'))}, {q(x.get('voltage'))}, ST_SetSRID(ST_MakePoint({x['lon']}, {x['lat']}), 4326)) ON CONFLICT DO NOTHING;")
    batched(osm)
    print("reference tables", len(st), "states", len(co), "counties", len(osm), "stations", flush=True)


def main(schema_only=False, refs_only=False):
    run(schema_sql())
    extra = "\n".join(table_ddl(t) for t in TABLES)  # tables that modules create themselves
    if extra.strip():
        run("SET search_path = planner, extensions;\n" + extra)
    print("schema ready", flush=True)
    if refs_only:
        return reference_tables()
    if schema_only:
        return
    run("TRUNCATE " + ", ".join(f"planner.{t}" for t in TABLES) + " CASCADE;")
    for t in TABLES:
        rows, batch, n = dump(t), [], 0
        for ln in rows + [None]:
            if ln is None or sum(map(len, batch)) + len(ln) > CHUNK:
                if batch:
                    run("SET search_path = planner, extensions;\n" + "\n".join(batch))
                    n += len(batch)
                batch = []
            if ln is not None:
                batch.append(ln)
        if run(f"SELECT pg_get_serial_sequence('planner.{t}', 'id') AS s")[0]["s"]:  # keep serial ids ahead of the copied rows
            run(f"SELECT setval(pg_get_serial_sequence('planner.{t}', 'id'), coalesce(max(id), 1)) FROM planner.{t};")
        print(t, "inserts", n, flush=True)
    print(run("SELECT (SELECT count(*) FROM planner.job) AS jobs, (SELECT count(*) FROM planner.opportunity) AS overlaps, "
              "(SELECT count(*) FROM planner.org) AS utilities"))


    reference_tables()


if __name__ == "__main__":
    main("schema" in sys.argv[1:], "refs" in sys.argv[1:])
