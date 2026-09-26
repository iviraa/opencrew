"""Load every regional planner list, then rebuild overlaps: `uv run python -m scripts.load_national [recompute]`."""
import sys
import time

from app.db import connect
from app.engine.overlap import recompute
from app.ingest.national import ctpc, ercot, fl_tysp, isone, miso, nyiso, pjm, sertp, spp, west

LOADERS = [("MISO", miso.load), ("SPP", spp.load), ("PJM", pjm.load), ("ISO-NE", isone.load), ("NYISO", nyiso.load),
           ("ERCOT", ercot.load), ("CTPC", ctpc.load), ("FL PSC", fl_tysp.load), ("SERTP", sertp.load), ("West", west.load)]


def main(only_recompute=False):
    if not only_recompute:
        for name, fn in LOADERS:
            t = time.time()
            with connect() as conn:  # one commit per planner, so a failure keeps the others
                try:
                    fn(conn)
                except Exception as e:
                    conn.rollback()
                    print(f"{name} FAILED: {e}", flush=True)
                    continue
            print(f"{name} done in {time.time() - t:.0f}s", flush=True)
    with connect() as conn:
        print(recompute(conn, "long"), flush=True)
        rows = conn.execute("""SELECT o.state, o.id, count(DISTINCT j.id) AS jobs,
                                      (SELECT count(*) FROM job_review r WHERE r.org_id = o.id) AS review,
                                      (SELECT count(*) FROM opportunity op JOIN job a ON a.id = op.job_a JOIN job b ON b.id = op.job_b
                                        WHERE op.horizon = 'long' AND o.id IN (a.org_id, b.org_id)) AS overlaps
                               FROM org o LEFT JOIN job j ON j.org_id = o.id AND j.horizon = 'long'
                               WHERE o.kind = 'utility' GROUP BY o.state, o.id ORDER BY o.state""").fetchall()
    for r in rows:
        print(f"{r['state'] or '--'} {r['id']:<22} placed {r['jobs']:>4}  review {r['review']:>4}  overlaps {r['overlaps']:>4}")


if __name__ == "__main__":
    main("recompute" in sys.argv[1:])
