import os

import httpx

from app.geo.geolocate import km

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.displayName,places.formattedAddress,places.location,places.nationalPhoneNumber,places.websiteUri,places.rating"
SERVICES = ["crane rental", "equipment rental", "utility contractor"]


def midpoint(conn, opp_id):
    return conn.execute("SELECT ST_Y(c) AS lat, ST_X(c) AS lon FROM (SELECT ST_Centroid(link::geometry) AS c FROM opportunity WHERE id = %s) t",
                        (opp_id,)).fetchone()


def search(lat, lon, service="crane rental", radius_km=40):
    key = os.environ.get("GOOGLE_PLACES_KEY")
    if not key:
        raise RuntimeError("vendor search needs GOOGLE_PLACES_KEY")
    r = httpx.post(URL, timeout=20, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS}, json={
        "textQuery": service, "maxResultCount": 10,
        "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": min(radius_km, 50) * 1000.0}}})
    r.raise_for_status()
    out = []
    for p in r.json().get("places", []):
        loc = p.get("location", {})
        d = km((lat, lon), (loc.get("latitude", lat), loc.get("longitude", lon)))
        if d <= radius_km:
            out.append({"name": p.get("displayName", {}).get("text"), "address": p.get("formattedAddress"), "phone": p.get("nationalPhoneNumber"),
                        "website": p.get("websiteUri"), "rating": p.get("rating"), "distance_km": round(d, 1),
                        "lat": loc.get("latitude"), "lon": loc.get("longitude")})
    return sorted(out, key=lambda v: v["distance_km"])
