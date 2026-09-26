from app.storm import news
from scripts import fetch_osm, load_helene, load_jobs, load_layers, validate

if __name__ == "__main__":
    fetch_osm.main()  # named substations and plants, cached per tile
    fetch_osm.lines()  # transmission lines for routing and the grid layer, cached per tile
    print("articles", news.collect_replay())  # helene news sample, cached
    load_layers.main()  # state lines, tracts, fema nri, cdc svi, grid lines
    load_helene.main()  # storm events, utility substations, incidents
    load_jobs.main()  # filings, geolocation, phases, restoration, overlaps
    validate.main()
