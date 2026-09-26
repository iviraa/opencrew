"""Copy the planner's GIS tables into Supabase (schema `planner`, PostGIS) over HTTPS: works on networks that block port 5432.

Needs SUPABASE_ACCESS_TOKEN (a personal access token) and SUPABASE_PROJECT_REF. Safe to rerun: each table is emptied and reloaded.
"""
import os
import re
import subprocess
import sys

import httpx

from app.db import ROOT

TABLES = ["org", "source_doc", "job", "job_version", "job_review", "opportunity", "tract", "asset", "grid_line", "job_hazard"]  # parents first
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


SNAPSHOT = {"job_version": "", "job": "ORDER BY parent_job_id IS NOT NULL"}  # hypertable chunks and parents-before-phases need a plain, ordered copy


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


def main(schema_only=False):
    run(schema_sql())
    print("schema ready", flush=True)
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
        seq = f"SELECT setval(pg_get_serial_sequence('planner.{t}', 'id'), coalesce(max(id), 1)) FROM planner.{t};"
        if t in ("source_doc", "job_review"):
            run(seq)  # keep serial ids ahead of the copied rows
        print(t, "inserts", n, flush=True)
    print(run("SELECT (SELECT count(*) FROM planner.job) AS jobs, (SELECT count(*) FROM planner.opportunity) AS overlaps, "
              "(SELECT count(*) FROM planner.org) AS utilities"))


if __name__ == "__main__":
    main("schema" in sys.argv[1:])
