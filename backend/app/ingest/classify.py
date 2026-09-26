import re
from datetime import date

KV = re.compile(r"(\d{2,3})(?:\.\d+)?(?:\s*[-/]\s*\d{1,3}(?:\.\d+)?)?\s*kV", re.I)
PREFIX = re.compile(r"^(SAV|GTC|MEAG|DU|GRID)\s*:\s*", re.I)
DASH = re.compile(r"\s*[-–—]\s*")
EQUIPMENT = re.compile(r"reactor|relay|breaker|capacitor|\bbus\b|transformer|autobank|\bbank\b|switch", re.I)
UPGRADE = re.compile(r"rebuild|reconductor|upgrade|uprate|replace", re.I)
NEW = re.compile(r"construct|\bnew\b|\badd\b", re.I)


def voltage(name):
    kvs = [int(m.group(1)) for m in KV.finditer(name)]
    return max(kvs) if kvs else None


def endpoints(name):
    head = PREFIX.sub("", name)
    m = KV.search(head)
    head = (head[:m.start()] if m else head).split(":")[0]
    return [p.strip(" ,&/") for p in DASH.split(head) if p.strip(" ,&/")][:2]


def job_type(name):
    if len(endpoints(name)) < 2 or EQUIPMENT.search(name):
        return "substation"
    return "new_line" if NEW.search(name) and not UPGRADE.search(name) else "line_upgrade"


def shift_months(d, months):
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, min(d.day, 28))


DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")


def parse_date(s):
    dates = [date(int(y) + 2000 if len(y) == 2 else int(y), int(m), int(d)) for m, d, y in DATE.findall(s)]
    return max(dates)  # phased projects list several; last one is final in-service
