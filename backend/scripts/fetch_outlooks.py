import sys

from app.db import connect, init_schema
from app.storm import hazards, outlook


def main(what=("live", "helene", "hazards")):
    with connect() as conn:
        init_schema(conn)
        if "live" in what:
            print("live outlooks", outlook.fetch_live(conn))
        if "helene" in what:
            print("helene outlooks", outlook.fetch_helene(conn))
        if "hazards" in what:
            print("long-range hazards", hazards.compute(conn))


if __name__ == "__main__":
    main([a.lstrip("-") for a in sys.argv[1:]] or ("live", "helene", "hazards"))
