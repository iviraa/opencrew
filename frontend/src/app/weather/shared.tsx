import type { Jobs } from "../data";

export type Scenario = "now" | "helene";

export function Split({ map, side }: { map: React.ReactNode; side: React.ReactNode }) {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,3fr)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] gap-5">
      <div className="min-h-0">{map}</div>
      <aside className="slide-in flex min-h-0 min-w-0 flex-col">{side}</aside>
    </div>
  );
}

export function ScenarioSwitch({ value, onChange }: { value: Scenario; onChange: (s: Scenario) => void }) {
  return (
    <div className="mb-3 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
      {([["now", "Right now"], ["helene", "Helene 2024 replay"]] as const).map(([k, label]) => (
        <button key={k} onClick={() => onChange(k)} className={`flex-1 rounded-full py-1 ${value === k ? "bg-white shadow-sm" : "text-muted"}`}>{label}</button>
      ))}
    </div>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-2 flex items-center gap-1.5 px-2 text-xs font-semibold uppercase tracking-wide text-faint">{children}</h3>;
}

export const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features });

export const splitGeoms = (fs: GeoJSON.Feature[]) => ({
  lines: fs.filter((f) => f.geometry?.type !== "Point"),
  points: fs.filter((f) => f.geometry?.type === "Point"),
});

// a box around a point, for flying the map to one spot
export const around = (lon: number, lat: number, d = 0.15): [number, number, number, number] => [lon - d, lat - d * 0.7, lon + d, lat + d * 0.7];

function coords(g: GeoJSON.Geometry | null): GeoJSON.Position[] {
  if (!g) return [];
  if (g.type === "Point") return [g.coordinates];
  if (g.type === "LineString" || g.type === "MultiPoint") return g.coordinates;
  if (g.type === "Polygon" || g.type === "MultiLineString") return g.coordinates.flat();
  if (g.type === "MultiPolygon") return g.coordinates.flat(2);
  if (g.type === "GeometryCollection") return g.geometries.flatMap(coords);
  return [];
}

function miles(a: GeoJSON.Position, lon: number, lat: number) {
  const r = Math.PI / 180, dLat = (a[1] - lat) * r, dLon = (a[0] - lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat * r) * Math.cos(a[1] * r) * Math.sin(dLon / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.sqrt(h));
}

// closest of our projects to a spot, by nearest vertex (good enough at map scale)
export function nearestProject(projects: Jobs | null, lon: number, lat: number) {
  let best: { name: string; id: string; mi: number } | null = null;
  for (const f of projects?.features ?? []) {
    for (const c of coords(f.geometry)) {
      const mi = miles(c, lon, lat);
      if (!best || mi < best.mi) best = { name: f.properties.name, id: f.properties.id, mi };
    }
  }
  return best;
}

export const when = (s: string, replay: boolean, ago: (s: string) => string) =>
  replay ? new Date(s).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ago(s);
