import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";
import type { JobCollection, Opportunity } from "../api";
import { TIER_COLOR, TIER_LABEL } from "../format";

type Props = {
  jobs: JobCollection | null;
  opportunities: Opportunity[];
  selected: Opportunity | null;
  onSelect: (id: number) => void;
  fly: { bbox: [number, number, number, number]; at: number } | null;
};

maplibregl.setWorkerUrl(workerUrl); // v6 needs an explicit worker once bundled

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const tierColor = ["match", ["get", "tier"], ...Object.entries(TIER_COLOR).flat(), "#64748b"] as unknown as maplibregl.ExpressionSpecification;

function oppFeatures(opps: Opportunity[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: opps.flatMap((o) => {
      const [p, q] = o.link.coordinates;
      const mid = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
      const props = { id: o.id, tier: o.tier, score: o.score };
      return [
        { type: "Feature", properties: props, geometry: o.link },
        { type: "Feature", properties: { ...props, marker: true }, geometry: { type: "Point", coordinates: mid } },
      ] as GeoJSON.Feature[];
    }),
  };
}

function bounds(coords: number[][]): LngLatBoundsLike {
  const xs = coords.map((c) => c[0]);
  const ys = coords.map((c) => c[1]);
  return [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]];
}

function coordsOf(g: GeoJSON.Geometry): number[][] {
  if (g.type === "Point") return [g.coordinates];
  if (g.type === "LineString") return g.coordinates;
  return [];
}

export default function MapView({ jobs, opportunities, selected, onSelect, fly }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [loaded, setLoaded] = useState(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const m = new maplibregl.Map({ container: box.current!, style: STYLE, center: [-81.6, 32.9], zoom: 6.3 });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("jobs", { type: "geojson", data: EMPTY });
      m.addSource("opps", { type: "geojson", data: EMPTY });
      const faded = ["case", ["<", ["get", "confidence"], 0.7], 0.45, 0.95] as maplibregl.ExpressionSpecification;
      m.addLayer({ id: "opp-links", type: "line", source: "opps", filter: ["!", ["has", "marker"]],
        paint: { "line-color": tierColor, "line-width": 2, "line-dasharray": [1, 1.5], "line-opacity": 0.8 } });
      m.addLayer({ id: "job-lines", type: "line", source: "jobs", filter: ["all", ["==", ["geometry-type"], "LineString"], ["!=", ["get", "geom_quality"], "straight_line"]],
        layout: { "line-cap": "round" }, paint: { "line-color": ["get", "color"], "line-width": 3.5, "line-opacity": faded } });
      m.addLayer({ id: "job-lines-approx", type: "line", source: "jobs", filter: ["all", ["==", ["geometry-type"], "LineString"], ["==", ["get", "geom_quality"], "straight_line"]],
        paint: { "line-color": ["get", "color"], "line-width": 3, "line-dasharray": [2, 1.2], "line-opacity": faded } });
      m.addLayer({ id: "job-points", type: "circle", source: "jobs", filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": 5.5,
          "circle-color": ["case", ["==", ["get", "geom_quality"], "partial_point"], "#ffffff", ["get", "color"]],
          "circle-stroke-color": ["get", "color"], "circle-stroke-width": 2, "circle-opacity": faded, "circle-stroke-opacity": faded,
        } });
      m.addLayer({ id: "job-selected", type: "line", source: "jobs", filter: ["in", ["get", "id"], ["literal", []]],
        paint: { "line-color": "#0f172a", "line-width": 7, "line-opacity": 0.25 } });
      m.addLayer({ id: "opp-markers", type: "circle", source: "opps", filter: ["has", "marker"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "score"], 0, 7, 1, 13],
          "circle-color": tierColor, "circle-opacity": 0.2, "circle-stroke-color": tierColor, "circle-stroke-width": 2,
        } });
      m.addLayer({ id: "opp-selected", type: "circle", source: "opps", filter: ["all", ["has", "marker"], ["==", ["get", "id"], -1]],
        paint: { "circle-radius": 18, "circle-color": "transparent", "circle-stroke-color": "#0f172a", "circle-stroke-width": 3 } });

      m.on("click", "opp-markers", (e) => onSelectRef.current(Number(e.features![0].properties.id)));
      for (const layer of ["job-lines", "job-lines-approx", "job-points"]) {
        m.on("click", layer, (e) => {
          const p = e.features![0].properties;
          new maplibregl.Popup({ closeButton: false }).setLngLat(e.lngLat)
            .setHTML(`<b>${p.name}</b><br/>${p.org_name} · in service ${String(p.in_service).slice(0, 10)}`).addTo(m);
        });
      }
      for (const layer of ["opp-markers", "job-lines", "job-lines-approx", "job-points"]) {
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      }
      setLoaded(true);
    });
    map.current = m;
    return () => m.remove();
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;
    (m.getSource("jobs") as GeoJSONSource).setData(jobs ?? EMPTY);
    (m.getSource("opps") as GeoJSONSource).setData(oppFeatures(opportunities));
  }, [jobs, opportunities, loaded]);

  useEffect(() => {
    const m = map.current;
    if (!m || !loaded || !jobs) return;
    const ids = selected ? [selected.job_a, selected.job_b] : [];
    m.setFilter("job-selected", ["in", ["get", "id"], ["literal", ids]]);
    m.setFilter("opp-selected", ["all", ["has", "marker"], ["==", ["get", "id"], selected?.id ?? -1]]);
    const focus = (on: number, off: number) =>
      (selected ? ["case", ["==", ["get", "id"], selected.id], on, off] : on) as maplibregl.ExpressionSpecification;
    m.setPaintProperty("opp-links", "line-opacity", focus(0.9, 0.15));
    m.setPaintProperty("opp-markers", "circle-stroke-opacity", focus(1, 0.25));
    m.setPaintProperty("opp-markers", "circle-opacity", focus(0.2, 0.05));
    if (!selected) return;
    m.resize(); // detail panel may have just narrowed the map
    const coords = jobs.features.filter((f) => ids.includes(String(f.id))).flatMap((f) => coordsOf(f.geometry));
    if (coords.length) m.fitBounds(bounds(coords), { padding: 120, maxZoom: 11, duration: 900 });
  }, [selected, jobs, loaded]);

  useEffect(() => {
    if (!fly || !map.current) return;
    const [x0, y0, x1, y1] = fly.bbox;
    map.current.fitBounds([[x0, y0], [x1, y1]], { padding: 40, duration: 900 });
  }, [fly]);

  return (
    <div className="relative h-full w-full">
      <div ref={box} className="h-full w-full" />
      <Legend jobs={jobs} />
    </div>
  );
}

function Legend({ jobs }: { jobs: JobCollection | null }) {
  const orgs = new Map<string, string>();
  jobs?.features.forEach((f) => orgs.set(f.properties.org_name, f.properties.color));
  return (
    <div className="absolute left-3 top-3 rounded-lg bg-white/95 px-3 py-2 text-[11px] leading-4 shadow-md ring-1 ring-slate-200">
      {[...orgs].map(([name, color]) => (
        <div key={name} className="flex items-center gap-2 py-0.5">
          <span className="h-1 w-5 rounded" style={{ background: color }} /> {name}
        </div>
      ))}
      <div className="mt-2 flex items-center gap-2 py-0.5 text-slate-500">
        <span className="w-5 border-t-2 border-dashed border-slate-500" /> approx route (straight line)
      </div>
      <div className="flex items-center gap-2 py-0.5 text-slate-500">
        <span className="h-2.5 w-2.5 rounded-full border-2 border-slate-500 bg-white" /> one endpoint located
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {Object.entries(TIER_LABEL).map(([tier, label]) => (
          <span key={tier} className="flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: TIER_COLOR[tier as keyof typeof TIER_COLOR] }} /> {label}
          </span>
        ))}
      </div>
    </div>
  );
}
