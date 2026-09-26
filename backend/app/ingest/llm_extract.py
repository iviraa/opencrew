import json
import re
from datetime import date

from pydantic import BaseModel, ValidationError, field_validator

from app.config import DEFAULT_DURATION_MONTHS
from app.ingest.classify import endpoints, job_type, shift_months, voltage
from app.ingest.pdf import page_allowed
from app.llm import generate_json, provider

PAGES_PER_CALL = 8
SCHEMA = {"type": "object", "properties": {"projects": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "project_type": {"type": "string", "enum": ["new_line", "line_upgrade", "substation"]},
    "voltage_kv": {"type": "integer"}, "endpoints": {"type": "array", "items": {"type": "string"}},
    "in_service_date": {"type": "string", "description": "YYYY-MM-DD"}, "start_date": {"type": "string", "description": "YYYY-MM-DD if stated"},
    "description": {"type": "string"}, "page": {"type": "integer"}},
    "required": ["name", "in_service_date", "page"]}}}, "required": ["projects"]}
PROMPT = """Extract every planned transmission project from these utility filing pages. Copy names, dates and voltages exactly as written;
do not guess values that are not on the page. Endpoints are the substation names a line connects. Pages are marked === page N ===."""


class Row(BaseModel):
    name: str
    in_service_date: date
    page: int
    project_type: str | None = None
    voltage_kv: int | None = None
    endpoints: list[str] | None = None
    start_date: date | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def not_blank(cls, v):
        if len(v.strip()) < 3:
            raise ValueError("name too short")
        return v.strip()


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def extract(org, pages):
    if not provider():
        raise RuntimeError("this filing layout needs an LLM; set GEMINI_API_KEY or LOCAL_LLM_URL")
    allowed = [(i + 1, p) for i, p in enumerate(pages) if page_allowed(p)]  # CEII pages never leave the machine
    rows, bad = [], []
    for k in range(0, len(allowed), PAGES_PER_CALL):
        chunk = allowed[k:k + PAGES_PER_CALL]
        text = "\n".join(f"=== page {n} ===\n{p}" for n, p in chunk)
        for item in json.loads(generate_json(f"{PROMPT}\n\n{text}", SCHEMA) or "{}").get("projects", []):
            try:
                r = Row(**item)
            except ValidationError as e:
                bad.append({"reason": "failed schema validation", "page": item.get("page"), "raw": item, "errors": str(e)[:300]})
                continue
            if r.page not in dict(chunk):
                bad.append({"reason": "page outside the text it was given", "page": r.page, "raw": item})
                continue
            kind = r.project_type if r.project_type in DEFAULT_DURATION_MONTHS else job_type(r.name)
            start = r.start_date if r.start_date and r.start_date < r.in_service_date else shift_months(r.in_service_date, -DEFAULT_DURATION_MONTHS[kind])
            rows.append({"id": f"{org}-{slug(r.name)}", "org_id": org, "name": r.name, "ref": None, "description": r.description,
                         "status": None, "job_type": kind, "voltage_kv": r.voltage_kv or voltage(r.name),
                         "endpoints": r.endpoints or endpoints(r.name), "start": start, "in_service": r.in_service_date,
                         "window_basis": "filed" if r.start_date else "default_duration", "cost_usd": None, "source_page": r.page})
    return rows, bad
