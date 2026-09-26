"""The hazards that affect transmission construction work, and where each layer comes from."""
from app.db import ROOT

CACHE = ROOT / "data/layers/hazards"
RAW_EVENTS = ROOT / "data/raw/storm_events"
HEADERS = {"User-Agent": "opencrew/0.1 (hackathon)", "Accept": "application/geo+json, application/json"}
LIVE_TTL_H, OUTLOOK_TTL_H = 3, 6  # how old a cached live or outlook layer may get
CLIMATE_YEARS = list(range(2016, 2026))  # ten full years of NOAA Storm Events

HAZARDS = {  # key -> label, how it touches the work
    "wind": ("Wind", "crane lifts, tower erection and stringing"),
    "storms": ("Storms", "lightning stops aerial and live-line work"),
    "tornado": ("Tornado", "site and material damage"),
    "winter": ("Winter", "ice and snow stop aerial work and close access"),
    "heat": ("Heat", "crew safety limits shorten the day"),
    "flood": ("Flood", "access, excavation and laydown yards"),
    "tropical": ("Tropical", "everything stops; restoration takes crews"),
    "wildfire": ("Wildfire", "hot-work limits, clearing, closed access"),
    "earthquake": ("Earthquake", "rare, damages sites and substations"),
    "hail": ("Hail", "equipment and material damage"),
}

# NWS alert event names that matter for the work; the rest (marine, rip current, air quality...) are dropped
ALERT_EVENTS = {
    "High Wind Warning": "wind", "High Wind Watch": "wind", "Wind Advisory": "wind", "Extreme Wind Warning": "wind",
    "Severe Thunderstorm Warning": "storms", "Severe Thunderstorm Watch": "storms",
    "Tornado Warning": "tornado", "Tornado Watch": "tornado",
    "Winter Storm Warning": "winter", "Winter Storm Watch": "winter", "Ice Storm Warning": "winter", "Blizzard Warning": "winter",
    "Winter Weather Advisory": "winter", "Extreme Cold Warning": "winter", "Extreme Cold Watch": "winter", "Cold Weather Advisory": "winter",
    "Freezing Rain Advisory": "winter", "Heavy Freezing Spray Warning": "winter",
    "Excessive Heat Warning": "heat", "Excessive Heat Watch": "heat", "Extreme Heat Warning": "heat", "Extreme Heat Watch": "heat", "Heat Advisory": "heat",
    "Flood Warning": "flood", "Flood Watch": "flood", "Flash Flood Warning": "flood", "Flash Flood Watch": "flood", "Flood Advisory": "flood",
    "Coastal Flood Warning": "flood", "Storm Surge Warning": "tropical", "Storm Surge Watch": "tropical",
    "Hurricane Warning": "tropical", "Hurricane Watch": "tropical", "Tropical Storm Warning": "tropical", "Tropical Storm Watch": "tropical",
    "Red Flag Warning": "wildfire", "Fire Weather Watch": "wildfire", "Extreme Fire Danger": "wildfire",
}
ALERT_RANK = {"Warning": 3, "Watch": 2, "Advisory": 1}

# NOAA Storm Events EVENT_TYPE -> hazard (zone events like heat and winter storms come per forecast zone)
EVENT_TYPES = {
    "Thunderstorm Wind": "wind", "High Wind": "wind", "Strong Wind": "wind", "Marine Thunderstorm Wind": None, "Marine High Wind": None,
    "Lightning": "storms", "Tornado": "tornado", "Funnel Cloud": None, "Waterspout": None,
    "Winter Storm": "winter", "Ice Storm": "winter", "Heavy Snow": "winter", "Blizzard": "winter", "Winter Weather": "winter",
    "Extreme Cold/Wind Chill": "winter", "Cold/Wind Chill": "winter", "Sleet": "winter", "Frost/Freeze": None, "Lake-Effect Snow": "winter",
    "Excessive Heat": "heat", "Heat": "heat",
    "Flash Flood": "flood", "Flood": "flood", "Heavy Rain": "flood", "Coastal Flood": "flood", "Lakeshore Flood": "flood",
    "Hurricane": "tropical", "Hurricane (Typhoon)": "tropical", "Tropical Storm": "tropical", "Storm Surge/Tide": "tropical", "Tropical Depression": "tropical",
    "Wildfire": "wildfire", "Hail": "hail", "Marine Hail": None,
}

# FEMA National Risk Index county fields -> hazard (a long-run backup for months with thin history)
NRI_FIELDS = {"SWND_RISKS": "wind", "LTNG_RISKS": "storms", "TRND_RISKS": "tornado", "WNTW_RISKS": "winter", "ISTM_RISKS": "winter",
              "CWAV_RISKS": "winter", "HWAV_RISKS": "heat", "IFLD_RISKS": "flood", "CFLD_RISKS": "flood", "HRCN_RISKS": "tropical",
              "WFIR_RISKS": "wildfire", "ERQK_RISKS": "earthquake", "HAIL_RISKS": "hail"}

SOURCES = {
    "nws_alerts": {"title": "NWS active watches, warnings and advisories", "url": "https://api.weather.gov/alerts/active?status=actual"},
    "nws_zones": {"title": "NWS forecast zone to county correlation", "url": "https://www.weather.gov/source/gis/Shapefiles/County/bp05mr24.dbx"},
    "spc": {"title": "SPC convective outlooks, days 1-8", "url": "https://www.spc.noaa.gov/products/outlook/"},
    "spc_fire": {"title": "SPC fire weather outlooks, days 1-2", "url": "https://www.spc.noaa.gov/products/fire_wx/"},
    "wpc_ero": {"title": "WPC excessive rainfall outlook, days 1-5", "url": "https://www.wpc.ncep.noaa.gov/qpf/excess_rain.shtml"},
    "nhc": {"title": "NHC tropical weather outlook and wind speed probabilities", "url": "https://www.nhc.noaa.gov/gis/"},
    "wfigs": {"title": "NIFC WFIGS current wildfire perimeters and incidents", "url": "https://data-nifc.opendata.arcgis.com/"},
    "usgs": {"title": "USGS earthquakes, past 7 days, M2.5+", "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"},
    "cpc": {"title": "NOAA CPC temperature and precipitation outlooks (6-10 day, 8-14 day, weeks 3-4, monthly, seasonal)",
            "url": "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/"},
    "storm_events": {"title": "NOAA NCEI Storm Events Database, 2016-2025", "url": "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"},
    "nri": {"title": "FEMA National Risk Index, county risk by hazard",
            "url": "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0"},
    "counties": {"title": "Census county boundaries (cb_2023, 1:20m)", "url": "https://www2.census.gov/geo/tiger/GENZ2023/shp/"},
}

SPC_FIRE = "https://www.spc.noaa.gov/products/fire_wx/day{d}fw_{kind}.lyr.geojson"  # kind: dryt (dry thunderstorm) | windrh (wind and low humidity)
WFIGS = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/{layer}/FeatureServer/0/query"
WFIGS_LAYERS = {"perimeters": "WFIGS_Interagency_Perimeters_Current", "incidents": "WFIGS_Incident_Locations_Current"}
USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson"
CPC = "https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/{name}_latest.zip"
CPC_PRODUCTS = {"610": "6-10 day", "814": "8-14 day", "wk34": "weeks 3-4", "monthupd_": "monthly", "seas": "seasonal"}  # prefix of temp/prcp names
NRI_QUERY = "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0/query"
