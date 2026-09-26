import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef } from "react";

maplibregl.setWorkerUrl(workerUrl);  // v6 needs an explicit worker once bundled

const STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";  // quiet grey basemap so our colors carry the map
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const HOME: LngLatBoundsLike = [[-85.6, 30.4], [-78.6, 35.3]];  // georgia and south carolina

// every feature styles itself through properties: color, width, opacity, dash, radius, title, pick
export type Scene = { areas?: GeoJSON.FeatureCollection; lines?: GeoJSON.FeatureCollection; points?: GeoJSON.FeatureCollection };
export type Fit = { bbox: [number, number, number, number]; key: string | number; maxZoom?: number };

export function bboxOf(fcs: (GeoJSON.FeatureCollection | undefined)[]): [number, number, number, number] | null {
  let b: [number, number, number, number] | null = null;
  const add = (c: GeoJSON.Position) => {
    b = b ? [Math.min(b[0], c[0]), Math.min(b[1], c[1]), Math.max(b[2], c[0]), Math.max(b[3], c[1])] : [c[0], c[1], c[0], c[1]];
  };
  const walk = (g: GeoJSON.Geometry) => {
    if (g.type === "Point") add(g.coordinates);
    else if (g.type === "LineString" || g.type === "MultiPoint") g.coordinates.forEach(add);
    else if (g.type === "Polygon" || g.type === "MultiLineString") g.coordinates.flat().forEach(add);
    else if (g.type === "MultiPolygon") g.coordinates.flat(2).forEach(add);
    else if (g.type === "GeometryCollection") g.geometries.forEach(walk);
  };
  fcs.forEach((fc) => fc?.features.forEach((f) => f.geometry && walk(f.geometry)));
  return b;
}

export default function MapPane({ scene, fit, onPick, children }: {
  scene: Scene; fit?: Fit | null; onPick?: (pick: string) => void; children?: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const latest = useRef({ scene, fit, onPick });
  latest.current = { scene, fit, onPick };

  const push = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    const s = latest.current.scene;
    (m.getSource("areas") as GeoJSONSource).setData(s.areas ?? EMPTY);
    (m.getSource("lines") as GeoJSONSource).setData(s.lines ?? EMPTY);
    (m.getSource("points") as GeoJSONSource).setData(s.points ?? EMPTY);
  };

  useEffect(() => {
    const m = new maplibregl.Map({ container: box.current!, style: STYLE, bounds: HOME, attributionControl: { compact: true }, fadeDuration: 0 });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: "280px" });
    m.on("load", () => {
      for (const id of ["areas", "lines", "points"]) m.addSource(id, { type: "geojson", data: EMPTY });
      const num = (k: string, d: number) => ["coalesce", ["get", k], d] as maplibregl.ExpressionSpecification;
      const color = ["coalesce", ["get", "color"], "#5b2bb5"] as maplibregl.ExpressionSpecification;
      m.addLayer({ id: "areas-fill", type: "fill", source: "areas", paint: { "fill-color": color, "fill-opacity": num("opacity", 0.25) } });
      m.addLayer({ id: "areas-edge", type: "line", source: "areas", paint: { "line-color": color, "line-width": 1.5, "line-opacity": 0.7 } });
      m.addLayer({ id: "lines-halo", type: "line", source: "lines", filter: ["!=", ["get", "dash"], true],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": ["+", num("width", 3), 3], "line-opacity": num("opacity", 1) } });
      m.addLayer({ id: "lines-solid", type: "line", source: "lines", filter: ["!=", ["get", "dash"], true],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": color, "line-width": num("width", 3), "line-opacity": num("opacity", 1) } });
      m.addLayer({ id: "lines-dash", type: "line", source: "lines", filter: ["==", ["get", "dash"], true],
        paint: { "line-color": color, "line-width": num("width", 2.5), "line-opacity": num("opacity", 1), "line-dasharray": [1.5, 1.2] } });
      m.addLayer({ id: "points", type: "circle", source: "points",
        paint: { "circle-color": color, "circle-radius": num("radius", 6), "circle-opacity": num("opacity", 1),
                 "circle-stroke-color": ["coalesce", ["get", "stroke"], "#ffffff"], "circle-stroke-width": 2, "circle-stroke-opacity": num("opacity", 1) } });
      ready.current = true;
      push();
      const f = latest.current.fit;
      if (f) m.fitBounds(f.bbox, { padding: 60, maxZoom: f.maxZoom ?? 10, duration: 0 });
    });
    const hoverable = ["points", "lines-solid", "lines-dash", "areas-fill"];
    m.on("mousemove", (e) => {
      if (!ready.current) return;
      const hit = m.queryRenderedFeatures(e.point, { layers: hoverable }).find((f) => f.properties?.title);
      m.getCanvas().style.cursor = hit?.properties?.pick ? "pointer" : "";
      if (hit) tip.setLngLat(e.lngLat).setHTML(String(hit.properties.title)).addTo(m);
      else tip.remove();
    });
    m.on("mouseout", () => tip.remove());
    m.on("click", (e) => {
      const hit = m.queryRenderedFeatures(e.point, { layers: hoverable }).find((f) => f.properties?.pick);
      if (hit) latest.current.onPick?.(String(hit.properties.pick));
    });
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(box.current!);
    return () => { ro.disconnect(); tip.remove(); m.remove(); map.current = null; ready.current = false; };
  }, []);

  useEffect(push, [scene]);

  useEffect(() => {
    if (fit && ready.current) map.current?.fitBounds(fit.bbox, { padding: 60, maxZoom: fit.maxZoom ?? 10, duration: 900 });
  }, [fit?.key]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="pen-box relative h-full w-full overflow-hidden bg-soft">
      <div ref={box} style={{ position: "absolute", inset: 0 }} />{/* inline: maplibre css would make it relative */}
      {children}
    </div>
  );
}

export const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
