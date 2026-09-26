import sys
import time

from app.db import connect, init_schema
from app.storm import live

if __name__ == "__main__":
    every = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # seconds between polls, 0 = once
    while True:
        with connect() as conn:
            init_schema(conn)
            print(live.poll(conn), flush=True)
        if not every:
            break
        time.sleep(every)
