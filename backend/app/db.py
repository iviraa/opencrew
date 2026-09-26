import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:opencrew@localhost:5433/opencrew")


SEARCH_PATH = os.environ.get("DB_SEARCH_PATH")  # e.g. "planner, extensions, public" on supabase, where the planner tables live in their own schema


def connect():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
    if SEARCH_PATH:
        conn.execute(f"SET search_path TO {SEARCH_PATH}")  # poolers may drop the search_path option from the url
    return conn


def get_conn():
    with connect() as conn:  # commits on clean exit
        yield conn


def init_schema(conn, reset=False):
    if reset:
        conn.execute("DROP TABLE IF EXISTS outreach, contact, opportunity, job_version, job_review, job, source_doc, org CASCADE")  # keeps reference layers
    conn.execute((Path(__file__).parent / "schema.sql").read_text())
