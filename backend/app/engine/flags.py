import re
from datetime import timedelta

from rapidfuzz import fuzz

from app.geo.geolocate import norm

TIE = re.compile(r"\btie\b", re.I)


def in_hurricane_season(start, end):
    if end <= start:
        return False
    if end - start >= timedelta(days=366):
        return True
    d = start
    while d < end:
        if 6 <= d.month <= 11:
            return True
        d += timedelta(days=28)
    return 6 <= end.month <= 11


def flags(a, b, risk, a_start, a_end, b_start, b_end):
    out = []
    start, end = max(a_start, b_start), min(a_end, b_end)
    if risk >= 0.8 and in_hurricane_season(start, end):
        out.append("hurricane_season_high_risk")
    if TIE.search(a["name"]) or TIE.search(b["name"]):
        out.append("tie_line")
    ends_a, ends_b = [norm(e) for e in a["endpoints"] or []], [norm(e) for e in b["endpoints"] or []]
    if any(x and y and fuzz.token_set_ratio(x, y) >= 90 for x in ends_a for y in ends_b):  # "thurmond" vs "thurmond dam"
        out.append("shared_endpoint")
    return out
