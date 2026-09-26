"""All western loaders in one call: states without a public dated list (AK, HI) are left out on purpose."""
from app.ingest.national import aps, bpa, caiso, idahopower, nvenergy, pacificorp, pge_ltp, pse, westconnect

LOADERS = [caiso, westconnect, pge_ltp, pse, idahopower, nvenergy, aps, pacificorp, bpa]


def load(conn, only=None):
    out = {}
    for mod in LOADERS:
        out.update(mod.load(conn, only))
    return out
