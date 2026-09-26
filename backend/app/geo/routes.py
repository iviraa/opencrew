import heapq
import json
from collections import defaultdict
from functools import cache

from app.db import ROOT
from app.geo.geolocate import km

SNAP_KM = 0.15  # joins line ends inside the same substation yard
NEAR_KM = 1.5  # how far a line may end from the matched substation point
DETOUR = 1.6  # longest acceptable path vs straight distance


def cell(lon, lat, size=0.01):
    return int(lon // size), int(lat // size)


class LineGraph:
    def __init__(self):
        path = ROOT / "data/layers/osm_lines.json"
        self.ways = json.loads(path.read_text()) if path.exists() else []
        self.adj = defaultdict(list)  # node -> [(node, km, way index, forward)]
        self.grid = defaultdict(set)
        for i, w in enumerate(self.ways):
            c = w["coords"]
            if len(c) < 2:
                continue
            a, b = tuple(c[0]), tuple(c[-1])
            length = sum(km((p[1], p[0]), (q[1], q[0])) for p, q in zip(c, c[1:]))
            self.adj[a].append((b, length, i, True))
            self.adj[b].append((a, length, i, False))
            for n in (a, b):
                self.grid[cell(*n)].add(n)
        for n in list(self.adj):  # bridge small gaps between line ends
            for m in self.near(n, SNAP_KM):
                if m != n:
                    self.adj[n].append((m, km((n[1], n[0]), (m[1], m[0])), None, True))

    def near(self, p, radius_km):
        cx, cy = cell(*p)
        r = int(radius_km / 1.0) + 1  # cells are about 1 km
        return [n for dx in range(-r, r + 1) for dy in range(-r, r + 1) for n in self.grid.get((cx + dx, cy + dy), ())
                if km((p[1], p[0]), (n[1], n[0])) <= radius_km]

    def route(self, a, b):
        """a, b are (lon, lat); returns path coords or None."""
        straight = km((a[1], a[0]), (b[1], b[0]))
        limit = DETOUR * straight + 3
        ends = set(self.near(b, NEAR_KM))
        if not ends:
            return None
        dist, prev, heap = {}, {}, []
        for n in self.near(a, NEAR_KM):
            d = km((a[1], a[0]), (n[1], n[0]))
            dist[n] = d
            heapq.heappush(heap, (d, n))
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, 1e18) or d > limit:
                continue
            if n in ends:
                return self.coords(n, prev, a, b)
            for m, length, way, fwd in self.adj[n]:
                nd = d + length
                if nd < dist.get(m, 1e18) and nd <= limit:
                    dist[m], prev[m] = nd, (n, way, fwd)
                    heapq.heappush(heap, (nd, m))
        return None

    def coords(self, end, prev, a, b):
        parts, n = [], end
        while n in prev:
            p, way, fwd = prev[n]
            if way is not None:
                c = self.ways[way]["coords"]
                parts.append(c if fwd else c[::-1])
            n = p
        out = [list(a)]
        for part in reversed(parts):
            out += part
        return out + [list(b)]


@cache
def graph():
    return LineGraph()
