import ipaddress
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.db import ROOT
from app.engine.overlap import recompute
from app.engine.phases import build_phases
from app.geo.geolocate import Locator, register
from app.ingest import desc, gpc, llm_extract, pdf, pipeline

UPLOADS = ROOT / "data/raw/uploads"
MAX_BYTES = 50 * 1024 * 1024


def detect(pages):
    head = " ".join(pages[:2])
    if "Planned Transmission Projects $2M" in head and "Dominion Energy South Carolina" in head:
        return "desc", desc
    if any("Georgia ITS 10 Year Plan Project List" in p for p in pages):
        return "gpc", gpc
    return None, None


def save(content, name):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / f"{int(time.time())}_{name}"
    path.write_bytes(content)
    return path


def public_url(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("need an http(s) link")
    for info in socket.getaddrinfo(u.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("link points at a private address")  # no fetching the server's own network


def download(url):
    for _ in range(5):  # follow redirects by hand so every hop is checked
        public_url(url)
        with httpx.stream("GET", url, timeout=60, follow_redirects=False, headers={"User-Agent": "opencrew/0.1 (hackathon)"}) as r:
            if r.is_redirect:
                url = str(r.url.join(r.headers["location"]))
                continue
            r.raise_for_status()
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise ValueError("file is larger than 50 MB")
            return save(body, url.rstrip("/").split("/")[-1][:60] or "filing.pdf")
    raise ValueError("too many redirects")


def ingest(conn, path, org=None, org_name=None, state="SC", color="#16a34a", url=None):
    t0 = time.perf_counter()
    if path.read_bytes()[:4] != b"%PDF":
        return {"error": "not a PDF"}
    pages = pdf.read_pages(path)
    known, parser = detect(pages)
    org = known or org
    if not org:
        return {"error": "unknown layout: pass the utility id and name"}
    if not conn.execute("SELECT 1 FROM org WHERE id = %s", (org,)).fetchone():
        conn.execute("INSERT INTO org (id, name, color) VALUES (%s, %s, %s)", (org, org_name or org, color))
        conn.execute("INSERT INTO contact (org_id, role, email, is_demo) SELECT %s, role, email, TRUE FROM contact LIMIT 1", (org,))
    register(org, state, org_name or org) if not known else None
    doc_id, blocked = pipeline.add_doc(conn, org, path.name, pages, local_path=str(path.relative_to(ROOT)), url=url)
    if blocked:
        return {"error": "refused: document is marked CEII", "doc_id": doc_id}
    rows, bad = parser.parse(pages) if parser else llm_extract.extract(org, pages)
    stats = pipeline.store(conn, Locator(), org, doc_id, pages, rows, bad, datetime.now(timezone.utc), "parser" if parser else "llm")
    build_phases(conn)
    return {"org": org, "method": "parser" if parser else "gemini", "pages": len(pages), "rows": len(rows), **stats,
            "long": recompute(conn, "long"), "near": recompute(conn, "near"), "seconds": round(time.perf_counter() - t0, 1)}
