"""Utility news: `--org gpc,desc` (or `all`) rebuilds the lexicon, searches, classifies and stores. No flag keeps the Helene replay collector."""
import sys

from app.db import connect


def main(argv):
    if "--org" not in argv:
        from app.storm import news
        print("articles", news.collect_replay())  # hourly GDELT GKG samples + article text, cached under data/raw/helene/news
        return
    from app.news import feed
    who = argv[argv.index("--org") + 1]
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 90
    with connect() as conn:
        orgs = [r["id"] for r in conn.execute("SELECT id FROM org WHERE kind = 'utility' ORDER BY id").fetchall()] if who == "all" else who.split(",")
        totals = feed.run(conn, orgs, days)
    print({"fetched": sum(c["fetched"] for c in totals.values()), "linked": sum(c["linked"] for c in totals.values())})


if __name__ == "__main__":
    main(sys.argv[1:])
