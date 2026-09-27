"""The planner lists we refresh on our own: stable endpoints, stable ids, and the exact columns each loader reads."""
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field

import httpx

from app.db import ROOT

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
      "Accept": "*/*"}
MAX_BYTES = 60 * 1024 * 1024
PJM_BODY = ('{"GridName":"CostAllocation","ItemType":0,"Items":[],"Paginator":{"ItemType":7,"CurrentItmsPerPageValue":"10000",'
            '"CurrentPageIndex":"1"},"Sort":"","SortDirection":"","RelatedGridsFilters":""}')


@dataclass
class Source:
    key: str
    planner: str
    name: str
    module: str  # loader module under app.ingest.national
    manifest_url: str
    index_urls: list  # pages that list the current edition
    link_pattern: str | None  # href regex on those pages; None = the manifest url is the stable endpoint
    sheet: object  # sheet name, index, or a regex for sheets that carry a date in their name
    header: int
    columns: list  # every column the loader reads
    id_column: str
    date_column: str  # in-service dates; must parse for most rows that carry one
    cadence_days: int
    ext: str = "xlsx"
    post: str | None = None  # form body for an export endpoint
    zip_member: str | None = None  # regex of the member to pull out of a zip
    id_min_fill: float = 0.9
    date_min_parse: float = 0.9
    edition_from: str | None = None  # regex with one group on the url/filename
    notes: str = ""
    timeout: int = 90  # seconds to wait on the planner's server; some exports are built on request
    probe: str | None = None  # a url template with {mon} and {year}: newest month that answers 200 wins
    prime: str | None = None  # a page to visit first, for the session cookie an export endpoint expects
    kwargs: dict = field(default_factory=dict)


SOURCES = {
    "pjm": Source("pjm", "PJM", "PJM project status and cost allocation export", "pjm",
                  "https://www.pjm.com/m/ProjectConst/ProjectConstructionUpgrades", [], None, "Data", 0,
                  ["Upgrade Id", "Description", "Project Type", "Voltage", "Cost Estimate", "Required Date", "Transmission Owner", "State",
                   "Location", "Equipment", "Task", "Status", "Driver", "Projected In Service Date", "ISA In-Service Date", "Revised In-Service Date"],
                  "Upgrade Id", "Projected In Service Date", 7, post=PJM_BODY, date_min_parse=0.5, timeout=600, prime="https://www.pjm.com/planning/m/project-construction",
                  notes="continuous export; the Export to Excel button posts this body and the server builds the workbook on request"),
    "miso": Source("miso", "MISO", "MISO MTEP Appendix A quarterly status report", "miso",
                   "https://cdn.misoenergy.org/Appendix%20A%20Status%20Report575959.xlsx",
                   ["https://www.misoenergy.org/planning/transmission-planning/mtep-appendix-a-status-report/",
                    "https://www.misoenergy.org/planning/transmission-planning/"],
                   r"https://cdn\.misoenergy\.org/Appendix(?:%20| )A(?:%20| )Status(?:%20| )Report\d+\.xlsx", 0, 2,
                   ["Submitting TO", "Planning Status", "State 1", "State 2", "Expected ISD", "Estimated Miles New", "Estimated Miles Upgrade",
                    "MTEP Project ID", "Facility ID", "Name", "Project", "Facility Description", "Max kV", "Project Type", "Current Cost", "From Sub", "To Sub"],
                   "Facility ID", "Expected ISD", 90, edition_from=r"Report(\d+)\.xlsx"),
    "spp": Source("spp", "SPP", "SPP transmission expansion plan (STEP) appendix 1", "spp",
                  "https://www.spp.org/Documents/76727/2026%20SPP%20Transmission%20Expansion%20(STEP)%20Plan.zip",
                  ["https://www.spp.org/engineering/transmission-planning/"],
                  r"/Documents/\d+/20\d\d SPP Transmission Expansion[^\"']*\.zip", 0, 13,
                  ["NTC ID", "Project ID", "Upgrade ID", "Project Owner", "State(s)", "Project Name", "Upgrade Name", "Project Type",
                   "Project Owner Indicated\nIn-Service Date", "RTO Determined Need Date", "Letter of Notification \nto Construct Issue Date",
                   "Baseline Cost Estimate", "Baseline Cost Estimate with Escalation", "Current Cost Estimate", "Project Status", "From Bus Name",
                   "To Bus Name", "Project Description/ Comments", "Voltages (kV)", "Number of New", "Number of Rebuild/Reconductor", "Number of Voltage Conversion"],
                  "Upgrade ID", "Project Owner Indicated\nIn-Service Date", 365, ext="zip", zip_member=r"Appendix\s*1.*\.xlsx$",
                  edition_from=r"(20\d\d)[^/]*STEP", date_min_parse=0.85),
    "ercot": Source("ercot", "ERCOT", "ERCOT TPIT report, no-cost edition", "ercot",
                    "https://www.ercot.com/files/docs/2022/03/02/ERCOT-July-Ad-Hoc-TPIT-No-Cost-071326-UPDATE.xlsx",
                    ["https://www.ercot.com/gridinfo/planning"], r"https://www\.ercot\.com/files/docs/\d{4}/\d{2}/\d{2}/[^\"'\s]*TPIT[^\"'\s]*No-?Cost[^\"'\s]*\.xlsx",
                    re.compile(r"^(Future|Planned)TPIT\d*NoCost$"), 1,
                    ["ERCOT Project Number", "Project Title (text, please start with location name first)", "Project Description (text)",
                     'Terminal "from" Location', 'Terminal "to" Location', 'Transmission Status "under construction, planned or conceptual"',
                     "Transmission Owner (text)", "Projected In-Service Date (Month/Yr)", "Service Level kV", "Trans Circuit Miles New",
                     "Trans Circuit Miles Rebuilt, Reconductored or Upgraded", "County Location for Substation or Starting Point for a Line",
                     "County Location for Ending Point for a Line (Optional for Substation projects)", "Planning Charter Tier "],
                    "ERCOT Project Number", "Projected In-Service Date (Month/Yr)", 30, edition_from=r"(\d{6})", date_min_parse=0.8),
    "westconnect": Source("westconnect", "WestConnect", "WestConnect public project list", "westconnect",
                          "https://doc.westconnect.com/Documents.aspx?NID=21174&dl=1", [], None, "All Projects", 0,
                          ["Sponsor", "Development", "InService", "Length", "Description", "Purpose", "Origin", "Termination", "StateTraversed",
                           "wcprojectID", "projectid", "ProjectName", "Voltage", "Drivers"],
                          "projectid", "InService", 180, ext="xlsm", date_min_parse=0.7, timeout=240, edition_from=r"NID=(\d+)", notes="document id url; a new edition gets a new NID"),
    "caiso": Source("caiso", "CAISO", "CAISO transmission development forum approved projects", "caiso",
                    "https://www.caiso.com/documents/approved-projects-transmission-planning-process-jul-2026.xlsx",
                    [], None, "PGaE", 0,
                    ["TP Project ID", "Project", "Project Status", "Expected Construction Start", "Notes", re.compile(r"^Current In-Service .* TDF$")],
                    "TP Project ID", re.compile(r"^Current In-Service .* TDF$"), 90, edition_from=r"process-([a-z]{3}-20\d\d)\.xlsx", date_min_parse=0.8,
                    probe="https://www.caiso.com/documents/approved-projects-transmission-planning-process-{mon}-{year}.xlsx",
                    notes="the library page is rendered by script, so editions are found by trying the month names"),
}

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def newest(links, src):
    """Pick the latest edition among discovered links: by month-year for caiso, by yymmdd/date path for ercot, by year for spp, else last."""
    links = list(dict.fromkeys(links))
    if src.key == "caiso":
        return max(links, key=lambda u: (int(re.search(r"-(20\d\d)\.xlsx", u).group(1)), MONTHS.get(re.search(r"process-([a-z]{3})-", u).group(1), 0)))
    if src.key == "ercot":
        return max(links, key=lambda u: re.search(r"/docs/(\d{4}/\d{2}/\d{2})/", u).group(1))
    if src.key == "spp":
        return max(links, key=lambda u: (re.search(r"(20\d\d)", u) or re.search(r"(\d+)", u)).group(1))
    return links[-1]


def candidates(src, today=None, months=14):
    """Edition urls a probed source may have published, newest first."""
    from datetime import date
    today = today or date.today()
    y, m = today.year, today.month + 1  # next month too: planners post a little early
    out = []
    for _ in range(months):
        if m > 12:
            y, m = y + 1, 1
        out.append(src.probe.format(mon=list(MONTHS)[m - 1], year=y))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def discover(src, get=None, head=None):
    """(url, edition, how): the current edition's link from the planner's index page, by probing month names, else the manifest url."""
    get = get or (lambda u: httpx.get(u, headers=UA, timeout=30, follow_redirects=True))
    head = head or (lambda u: httpx.head(u, headers=UA, timeout=30, follow_redirects=True))
    if src.probe:
        for url in candidates(src):
            try:
                if head(url).status_code == 200:
                    return url, edition_of(src, url), "probe"
            except httpx.HTTPError:
                continue
        return src.manifest_url, edition_of(src, src.manifest_url), "discovery_failed"
    if not src.link_pattern:
        return src.manifest_url, edition_of(src, src.manifest_url), "fixed"
    for page in src.index_urls:
        try:
            r = get(page)
            if r.status_code != 200:
                continue
            found = [m.group(0) for m in re.finditer(src.link_pattern, r.text)]
            if found:
                url = newest(found, src)
                if url.startswith("/"):
                    url = re.match(r"https?://[^/]+", page).group(0) + url
                return url.replace(" ", "%20"), edition_of(src, url), "index"
        except (httpx.HTTPError, AttributeError):
            continue
    return src.manifest_url, edition_of(src, src.manifest_url), "discovery_failed"


def edition_of(src, url):
    """What to call this edition: the id in its url, else the day a continuous export was pulled."""
    from datetime import date
    m = re.search(src.edition_from, url) if src.edition_from else None
    if m:
        return m.group(1)
    return f"export {date.today().isoformat()}" if src.post else url.rsplit("/", 1)[-1][:60]


def fetch(src, url, get=None, post=None):
    """The file's bytes with the source's quirks: a form post for exports, a member pulled from a zip, size cap and retries."""
    last = None
    for attempt in range(2):
        try:
            if src.post:
                r = (post or (lambda u, d: _export(src, u, d)))(url, {"jsonModel": src.post})
            else:
                r = (get or (lambda u: httpx.get(u, headers=UA, timeout=src.timeout, follow_redirects=True)))(url)
            r.raise_for_status()
            body = r.content
            if len(body) > MAX_BYTES:
                raise ValueError(f"{len(body)} bytes is over the {MAX_BYTES // 1024 // 1024} MB cap")
            if src.zip_member:
                z = zipfile.ZipFile(io.BytesIO(body))
                name = next((n for n in z.namelist() if re.search(src.zip_member, n, re.I)), None)
                if not name:
                    raise ValueError(f"no member matching {src.zip_member} in the zip: {z.namelist()[:5]}")
                body = z.read(name)
            if body[:2] not in (b"PK",):  # xlsx, xlsm and zip all start with PK
                raise ValueError(f"not a spreadsheet: starts with {body[:12]!r}")
            return body
        except (httpx.HTTPError, ValueError, zipfile.BadZipFile) as e:
            last = e
    raise RuntimeError(f"could not fetch {src.name}: {last}")


def _export(src, url, data):
    """An export built on request: the page first for its session cookie, then the form post, streamed slowly by the server."""
    with httpx.Client(headers={**UA, "Referer": src.prime or url}, timeout=httpx.Timeout(src.timeout, connect=30), follow_redirects=True) as c:
        if src.prime:
            c.get(src.prime)
        return c.post(url, data=data)


def staged_path(src, body):
    """Where a fetched edition sits until it is promoted: next to the loader's file, never over it."""
    sha = hashlib.sha256(body).hexdigest()
    folder = (ROOT / src_file(src)).parent / "refresh"
    folder.mkdir(parents=True, exist_ok=True)
    ext = "xlsm" if src.ext == "xlsm" else "xlsx"
    path = folder / f"{sha}.{ext}"
    if not path.exists():
        path.write_bytes(body)
    return path, sha


def src_file(src):
    """The relative path the loader reads (its FILE constant)."""
    import importlib
    return importlib.import_module(f"app.ingest.national.{src.module}").FILE
