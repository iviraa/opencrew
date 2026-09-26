from scripts import fetch_osm, load_helene, load_jobs, load_layers, validate

if __name__ == "__main__":
    load_layers.main()  # tracts, fema nri, cdc svi
    fetch_osm.main()  # cached per tile after the first run
    load_helene.main()  # storm events and utility substations
    load_jobs.main()  # filings, geolocation, phases, restoration, overlaps
    validate.main()
