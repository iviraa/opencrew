from datetime import date

from app.db import ROOT, connect, init_schema
from app.engine.overlap import recompute
from app.engine.phases import build_phases
from app.geo.geolocate import Locator
from app.ingest import desc, gpc, pdf, pipeline
from app.outreach import seed_contacts
from app.storm.restoration import build_restoration

ORGS = [("desc", "Dominion Energy South Carolina", "#2563eb"), ("gpc", "Georgia Power", "#dc2626")]
FILINGS = [
    ("desc", "DESC Planned Transmission Projects $2M+ (2024-2028)", "data/raw/desc_2024_2028_projects.pdf", desc, date(2024, 1, 1)),
    ("gpc", "Georgia Power 2025 IRP Vol. 3 Transmission Plan (public disclosure)", "data/raw/gpc_2025_irp_vol3.pdf", gpc, date(2024, 12, 31)),
]


def main():
    loc = Locator()
    with connect() as conn:
        init_schema(conn, reset=True)
        conn.cursor().executemany("INSERT INTO org (id, name, color) VALUES (%s, %s, %s)", ORGS)
        seed_contacts(conn)
        for org, title, rel, parser, observed in FILINGS:
            pages = pdf.read_pages(ROOT / rel)
            doc_id, blocked = pipeline.add_doc(conn, org, title, pages, local_path=rel)
            if blocked:
                print("CEII: skipped", title)
                continue
            rows, bad = parser.parse(pages)
            print(org, dict(pipeline.store(conn, loc, org, doc_id, pages, rows, bad, observed)))
        print(recompute(conn, "long"))
        print("phases", build_phases(conn), recompute(conn, "near"))
        print("restoration", build_restoration(conn), recompute(conn, "emergency"))


if __name__ == "__main__":
    main()
