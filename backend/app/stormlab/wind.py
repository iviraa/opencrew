"""A tropical wind field for a what-if storm: Saffir-Simpson category, typical wind radii, a straight track that decays inland."""
import math
from datetime import timedelta
from functools import lru_cache

from shapely.geometry import MultiPoint, Point
from shapely.ops import unary_union

SOURCES = {
    "nhc_sshws": {"title": "NHC Saffir-Simpson Hurricane Wind Scale", "url": "https://www.nhc.noaa.gov/aboutsshws.php"},
    "nhc_radii": {"title": "NHC tropical cyclone forecast/advisory: 34, 50 and 64 kt wind radii", "url": "https://www.nhc.noaa.gov/aboutnhcprod.shtml"},
    "nhc_helene": {"title": "NHC Hurricane Helene advisories (forecast wind radii)", "url": "https://www.nhc.noaa.gov/archive/2024/HELENE.shtml"},
}
CATEGORY_MPH = {"ts": (39, 73), 1: (74, 95), 2: (96, 110), 3: (111, 129), 4: (130, 156), 5: (157, 200)}  # sustained wind, nhc_sshws
TYPICAL_RADII_NM = {  # 34 / 50 / 64 kt radii by category: estimates in the range NHC advisories show for Atlantic storms (nhc_radii, nhc_helene)
    "ts": (90, 30, 0), 1: (100, 50, 25), 2: (120, 60, 35), 3: (140, 70, 45), 4: (160, 80, 55), 5: (180, 90, 65),
}
TORNADO_MPH = {"EF0": (65, 85), "EF1": (86, 110), "EF2": (111, 135), "EF3": (136, 165), "EF4": (166, 200), "EF5": (200, 260)}  # nws_ef
TORNADO_RADII_NM = (1.5, 1.0, 0.6)  # a narrow path, roughly a mile wide: an estimate, not a track model
NM_KM = 1.852
FORWARD_MPH = 15  # typical landfalling forward speed; a knob
HOURS_BEFORE, HOURS_AFTER = 12, 36  # the field is drawn from offshore approach to a day and a half inland
DECAY_FLOOR, DECAY_HOURS = 0.35, 24  # winds and radii fall to 35% over the first day over land, then hold (a weakening tropical storm)
KT_MPH = {34: 39, 50: 58, 64: 74}  # band thresholds in sustained mph


def category_of(max_wind_mph):
    for cat, (lo, hi) in CATEGORY_MPH.items():
        if lo <= max_wind_mph <= hi:
            return cat
    return 5 if max_wind_mph > 156 else "ts"


def wind_of(category):
    lo, hi = CATEGORY_MPH.get(category) or TORNADO_MPH[category]
    return (lo + hi) // 2


def parse_category(value):
    """1-5, 'ts', or an EF rating -> (category, note): out-of-range numbers are clamped and said so."""
    if value is None:
        return 3, None
    s = str(value).strip().upper().replace(" ", "")
    if s.startswith("EF") and s[2:].isdigit():
        return (f"EF{min(int(s[2:]), 5)}", None if int(s[2:]) <= 5 else "tornado ratings stop at EF5; using EF5")
    if s in ("TS", "TROPICALSTORM"):
        return "ts", None
    try:
        n = int(float(s))
    except ValueError:
        return 3, f"category {value!r} not understood; using category 3"
    if n < 1:
        return "ts", f"category {n} is below the hurricane scale; using a tropical storm"
    if n > 5:
        return 5, f"category {n} is beyond the scale; using category 5"
    return n, None


def km(a_lon, a_lat, b_lon, b_lat):
    la1, la2 = math.radians(a_lat), math.radians(b_lat)
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b_lon - a_lon) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def circle(lon, lat, radius_km, n=24):
    if radius_km <= 0:
        return None
    ring = [(lon + radius_km * math.sin(math.radians(d)) / (111.32 * math.cos(math.radians(lat))), lat + radius_km * math.cos(math.radians(d)) / 110.57)
            for d in range(0, 360, 360 // n)]
    return MultiPoint(ring).convex_hull


def track(lon, lat, landfall, heading_deg=20.0, speed_mph=FORWARD_MPH):
    """Hourly centers from offshore approach to inland: (time, lon, lat, hours_since_landfall)."""
    step_km = speed_mph * 1.609
    for h in range(-HOURS_BEFORE, HOURS_AFTER + 1):
        d = step_km * h
        dlat = d * math.cos(math.radians(heading_deg)) / 110.57
        dlon = d * math.sin(math.radians(heading_deg)) / (111.32 * math.cos(math.radians(lat)))
        yield landfall + timedelta(hours=h), lon + dlon, lat + dlat, h


def decay(hours_after_landfall):
    return 1.0 if hours_after_landfall <= 0 else max(DECAY_FLOOR, 1 - (1 - DECAY_FLOOR) * hours_after_landfall / DECAY_HOURS)


def field(lon, lat, landfall, category, heading_deg=20.0, speed_mph=FORWARD_MPH, radii_nm=None):
    """Bands swept by 34, 50 and 64 kt winds along the track: {34: polygon|None, 50: ..., 64: ...} plus hourly circles for timing."""
    r34, r50, r64 = radii_nm or (TORNADO_RADII_NM if category in TORNADO_MPH else TYPICAL_RADII_NM[category])
    hourly = []  # (t, hours, {kt: circle})
    peak = wind_of(category)
    for t, clon, clat, h in track(lon, lat, landfall, heading_deg, speed_mph):
        f = decay(h)
        hourly.append((t, h, {kt: circle(clon, clat, r * NM_KM * f) if peak * f >= KT_MPH[kt] else None for kt, r in ((34, r34), (50, r50), (64, r64))}))
    bands = {}
    for kt in (34, 50, 64):
        shapes = [c[kt] for _, _, c in hourly if c[kt] is not None and c[kt].area > 0]
        bands[kt] = unary_union(shapes) if shapes else None
    return {"bands": bands, "hourly": hourly, "category": category, "radii_nm": (r34, r50, r64), "heading_deg": heading_deg, "speed_mph": speed_mph}


def band_of(wf, lon, lat):
    """Strongest band a point sits in (64, 50, 34) or None, and the hours it spends inside 34 kt winds."""
    p = Point(lon, lat)
    strongest = next((kt for kt in (64, 50, 34) if wf["bands"][kt] is not None and wf["bands"][kt].contains(p)), None)
    hours = sum(1 for _, _, c in wf["hourly"] if c[34] is not None and c[34].contains(p))
    return strongest, hours


@lru_cache
def _bands_helene():
    from datetime import timedelta as td

    from app.storm import briefing, helene
    adv = briefing.advisory_at(helene.LANDFALL - td(hours=12))
    if not adv:
        return None
    fb = None if adv["has_radii"] else briefing.DEFAULTS["default_r34_nm"]
    return {"bands": {34: briefing.band(adv, "r34", fb), 50: briefing.band(adv, "r50"), 64: briefing.band(adv, "r64")},
            "hourly": [], "category": 4, "radii_nm": None, "advisory": adv["advisory"], "issued": adv["issued"].isoformat(),
            "landfall": helene.LANDFALL, "name": "Helene", "radii_source": "NHC forecast wind radii" if adv["has_radii"] else "assumed radius"}


def helene_field():
    return _bands_helene()
