import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, LngLatBoundsLike } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef, useState } from "react";
import { api, type JobCollection, type Opportunity, type StormFrame } from "../api";
import { Layers, X } from "lucide-react";
import { DESC_COLOR, FAR_COLOR, GPC_COLOR, QUALITY_LABEL, TIER_COLOR, TIER_LABEL, monthYear, title } from "../format";
import { kindColorExpression } from "./IncidentCard";

type Props = {
  jobs: JobCollection | null;
  opportunities: Opportunity[];
  selected: Opportunity | null;
  onSelect: (id: number) => void;
  fly: { bbox: [number, number, number, number]; at: number } | null;
  storm: StormFrame | null;
  onMapClick?: ((lon: number, lat: number) => void) | null;
  hoverKey: string | null;
  onHover: (key: string | null) => void;
  zone?: GeoJSON.Feature | null;
  onIncident?: (id: number) => void;
};

maplibregl.setWorkerUrl(workerUrl); // v6 needs an explicit worker once bundled

const STYLE = "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json";  // carto voyager: soft, colorful, free with attribution
const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const ROW_KEY = ["coalesce", ["get", "parent_job_id"], ["get", "id"]] as maplibregl.ExpressionSpecification;  // phases share their project's row
const tierColor = ["case", ["get", "far"], FAR_COLOR, ["match", ["get", "tier"], ...Object.entries(TIER_COLOR).flat(), FAR_COLOR]] as unknown as maplibregl.ExpressionSpecification;
const incidentColor = kindColorExpression as unknown as maplibregl.ExpressionSpecification;

const esc = (v: unknown) => String(v ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);  // popup text comes from filings and storm reports
const present = (v: unknown) => v != null && v !== "null" && v !== "";
const stamp = (iso: unknown) => new Date(String(iso)).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function jobPopup(p: Record<string, unknown>) {
  const kind = `${title(String(p.job_type))}${present(p.voltage_kv) ? ` · ${p.voltage_kv} kV` : ""}${present(p.phase) ? ` · ${p.phase}` : ""}`;
  const quality = `${QUALITY_LABEL[String(p.geom_quality)] ?? p.geom_quality} · ${Math.round(Number(p.confidence) * 100)}% location confidence`;
  const when = p.job_type === "restoration"
    ? `Restoration window ${stamp(p.start_at)} → ${stamp(p.end_at)} ET`
    : `Work ${monthYear(String(p.start_at))} → ${monthYear(String(p.end_at))} · in service ${String(p.in_service).slice(0, 10)}`;
  const source = present(p.source_title) ? `${p.source_title}${present(p.source_page) ? `, p.${p.source_page}` : ""}` : "";
  const reports = p.job_type === "restoration" && present(p.description) ? String(p.description).slice(0, 320) : "";
  return `<div style="max-width:290px;line-height:1.4">
    <div style="color:${esc(p.color)};font-weight:600;font-size:12px">${esc(p.org_name)}</div>
    <div style="font-family:Fredoka,Figtree,sans-serif;font-weight:600;font-size:16px;margin:2px 0 6px">${esc(p.name)}</div>
    <div>${esc(kind)}</div><div>${esc(when)}</div>
    <div style="color:#5e6a8a;margin-top:4px">${esc(quality)}</div>
    ${source ? `<div style="color:#8a94b0;font-size:12px;margin-top:4px">${esc(source)}</div>` : ""}
    ${reports ? `<div style="margin-top:6px;color:#1b2447">${esc(reports)}</div>` : ""}
  </div>`;
}

const far = (o: Opportunity) => o.drive_min != null && o.drive_min > 45;

function oppFeatures(opps: Opportunity[]): GeoJSON.FeatureCollection {
  const links = opps.map((o) => ({ type: "Feature", properties: { id: o.id, tier: o.tier, score: o.score, far: far(o) }, geometry: o.link }));
  const spots = new Map<string, Opportunity[]>();  // pairs that meet at the same spot share one bubble
  for (const o of [...opps].sort((a, b) => b.score - a.score)) {
    const [p, q] = o.link.coordinates;
    const key = `${((p[0] + q[0]) / 2).toFixed(3)},${((p[1] + q[1]) / 2).toFixed(3)}`;
    spots.set(key, [...(spots.get(key) ?? []), o]);
  }
  const markers = [...spots.values()].map((group) => {
    const top = group[0];
    const [p, q] = top.link.coordinates;
    return { type: "Feature", geometry: { type: "Point", coordinates: [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2] },
      properties: { marker: true, id: top.id, ids: `,${group.map((o) => o.id).join(",")},`, count: group.length, tier: top.tier, score: top.score, far: group.every(far) } };
  });
  return { type: "FeatureCollection", features: [...links, ...markers] as GeoJSON.Feature[] };
}

function pickList(ids: number[], opps: Opportunity[], onPick: (id: number) => void) {
  const box = document.createElement("div");
  box.style.cssText = "max-height:340px;overflow-y:auto;overscroll-behavior:contain";
  const head = document.createElement("div");
  head.textContent = `${ids.length} team-ups meet here`;
  head.style.cssText = "font-family:Fredoka,Figtree,sans-serif;font-weight:600;font-size:15px;margin-bottom:6px";
  box.append(head);
  for (const id of ids) {
    const o = opps.find((x) => x.id === id);
    if (!o) continue;
    const b = document.createElement("button");
    b.style.cssText = "display:block;width:100%;text-align:left;padding:8px 10px;border-radius:12px;margin-top:2px;cursor:pointer";
    b.onmouseenter = () => (b.style.background = "#f5f8fd");
    b.onmouseleave = () => (b.style.background = "");
    const line = (color: string, text: string) => {
      const d = document.createElement("div");
      d.style.cssText = "display:flex;gap:8px;align-items:baseline;font-size:13px;font-weight:600;line-height:1.35";  // wrap so circuit numbers like #5 and #6 stay visible
      const dot = document.createElement("span");
      dot.style.cssText = `width:9px;height:9px;border-radius:9px;flex:none;background:${color}`;
      d.append(dot, document.createTextNode(text));  // text nodes, never html, since names come from filings
      return d;
    };
    const meta = document.createElement("div");
    meta.style.cssText = `font-size:12px;margin-top:2px;color:${far(o) ? "#e8590c" : "#12a36b"}`;
    meta.textContent = `${TIER_LABEL[o.tier]}, ${o.drive_min != null ? `${Math.round(o.drive_min)} min drive` : "drive not checked"}, save up to ${o.savings_high >= 1000 ? `$${Math.round(o.savings_high / 1000)}k` : `$${o.savings_high}`}`;
    const year = (iso: string) => new Date(iso).getFullYear();
    b.append(line(o.a_color, `${o.a_name}, starts ${year(o.a_start)}`), line(o.b_color, `${o.b_name}, starts ${year(o.b_start)}`), meta);
    b.onclick = () => onPick(id);
    box.append(b);
  }
  return box;
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

export default function MapView({ jobs, opportunities, selected, onSelect, fly, storm, onMapClick, hoverKey, onHover, zone, onIncident }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [layers, setLayers] = useState({ grid: false, risk: false, vulnerability: false });
  const tractsLoaded = useRef(false);
  const gridLoaded = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const clickRef = useRef(onMapClick);
  clickRef.current = onMapClick;
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const oppsRef = useRef(opportunities);
  oppsRef.current = opportunities;
  const incidentRef = useRef(onIncident);
  incidentRef.current = onIncident;

  useEffect(() => {
    const m = new maplibregl.Map({ container: box.current!, style: STYLE, center: [-81.6, 32.9], zoom: 6.3 });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("load", () => {
      m.addSource("tracts", { type: "geojson", data: EMPTY });
      for (const [key, color] of [["risk", "#dc2626"], ["vulnerability", "#7c3aed"]] as const) {
        m.addLayer({ id: `tract-${key}`, type: "fill", source: "tracts", layout: { visibility: "none" },
          paint: { "fill-color": color, "fill-opacity": ["interpolate", ["linear"], ["coalesce", ["get", key], 0], 0, 0, 1, 0.45] } });
      }
      m.addSource("zone", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "zone-fill", type: "fill", source: "zone", paint: { "fill-color": "#16a34a", "fill-opacity": 0.08 } });
      m.addLayer({ id: "zone-line", type: "line", source: "zone", paint: { "line-color": "#16a34a", "line-width": 1.5, "line-dasharray": [3, 2] } });
      m.addSource("grid", { type: "geojson", data: EMPTY });
      m.addLayer({ id: "grid", type: "line", source: "grid", layout: { visibility: "none" },
        paint: { "line-color": "#94a3b8", "line-opacity": 0.7,
          "line-width": ["interpolate", ["linear"], ["coalesce", ["get", "voltage"], 115], 115, 0.6, 230, 1.2, 500, 2.2] } });
      for (const src of ["cone", "track", "warnings", "reports", "staging", "incidents"]) m.addSource(src, { type: "geojson", data: EMPTY });
      m.addLayer({ id: "cone-fill", type: "fill", source: "cone", paint: { "fill-color": "#f43f5e", "fill-opacity": 0.12 } });
      m.addLayer({ id: "cone-line", type: "line", source: "cone", paint: { "line-color": "#e11d48", "line-width": 1.5, "line-dasharray": [2, 2] } });
      m.addLayer({ id: "warnings", type: "fill", source: "warnings",
        paint: { "fill-color": ["match", ["get", "phenomena", ["get", "payload"]], "TO", "#dc2626", "EW", "#9333ea", "SV", "#f59e0b", "#0ea5e9"], "fill-opacity": 0.25 } });
      m.addLayer({ id: "track", type: "line", source: "track", paint: { "line-color": "#881337", "line-width": 3 } });
      m.addSource("jobs", { type: "geojson", data: EMPTY });
      m.addSource("opps", { type: "geojson", data: EMPTY });
      const faded = ["case", ["<", ["get", "confidence"], 0.7], 0.45, 0.95] as maplibregl.ExpressionSpecification;
      m.addLayer({ id: "opp-links", type: "line", source: "opps", filter: ["!", ["has", "marker"]], layout: { "line-cap": "round" },
        paint: { "line-color": tierColor, "line-width": 3, "line-dasharray": [0.1, 1.8], "line-opacity": 0.9 } });  // round dots
      m.addLayer({ id: "job-casing", type: "line", source: "jobs", filter: ["==", ["geometry-type"], "LineString"], layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 5, 11, 9], "line-opacity": 0.9 } });
      m.addLayer({ id: "job-lines", type: "line", source: "jobs", filter: ["all", ["==", ["geometry-type"], "LineString"], ["!=", ["get", "geom_quality"], "straight_line"]],
        layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 6, 3, 11, 5], "line-opacity": faded } });
      m.addLayer({ id: "job-lines-approx", type: "line", source: "jobs", filter: ["all", ["==", ["geometry-type"], "LineString"], ["==", ["get", "geom_quality"], "straight_line"]],
        layout: { "line-cap": "round" }, paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 6, 3, 11, 5], "line-dasharray": [1.5, 1.5], "line-opacity": faded } });
      m.addLayer({ id: "job-points", type: "circle", source: "jobs", filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 6, 5, 11, 8],
          "circle-color": ["case", ["==", ["get", "geom_quality"], "partial_point"], "#ffffff", ["get", "color"]],
          "circle-stroke-color": ["case", ["==", ["get", "geom_quality"], "partial_point"], ["get", "color"], "#ffffff"], "circle-stroke-width": 2.5,
          "circle-opacity": faded, "circle-stroke-opacity": faded,
        } });
      m.addLayer({ id: "job-hit", type: "line", source: "jobs", filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#000", "line-width": 14, "line-opacity": 0.01 } });  // wide invisible target for hover and click
      m.addLayer({ id: "job-selected", type: "line", source: "jobs", filter: ["in", ["get", "id"], ["literal", []]],
        paint: { "line-color": "#1b2447", "line-width": 12, "line-opacity": 0.18, "line-blur": 2 } });
      m.addLayer({ id: "opp-glow", type: "circle", source: "opps", filter: ["has", "marker"],
        paint: { "circle-radius": ["interpolate", ["linear"], ["get", "score"], 0, 16, 1.3, 28], "circle-color": tierColor, "circle-opacity": 0.22, "circle-blur": 0.8 } });
      m.addLayer({ id: "opp-markers", type: "circle", source: "opps", filter: ["has", "marker"],
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "score"], 0, 7, 1.3, 13],
          "circle-color": tierColor, "circle-opacity": 1, "circle-stroke-color": "#ffffff", "circle-stroke-width": 3,
        } });
      m.addLayer({ id: "opp-count-bg", type: "circle", source: "opps", filter: ["all", ["has", "marker"], [">", ["get", "count"], 1]],
        paint: { "circle-radius": 9, "circle-color": "#1b2447", "circle-stroke-color": "#fff", "circle-stroke-width": 2, "circle-translate": [11, -11] } });
      m.addLayer({ id: "opp-count", type: "symbol", source: "opps", filter: ["all", ["has", "marker"], [">", ["get", "count"], 1]],
        layout: { "text-field": ["to-string", ["get", "count"]], "text-size": 11, "text-font": ["Montserrat Medium"], "text-offset": [0.95, -0.95], "text-allow-overlap": true, "text-ignore-placement": true },
        paint: { "text-color": "#ffffff" } });  // how many pairs share this bubble
      m.addLayer({ id: "reports", type: "circle", source: "reports",
        paint: { "circle-radius": 2, "circle-color": ["case", ["boolean", ["get", "power", ["get", "payload"]], false], "#e11d48", "#64748b"],
          "circle-opacity": 0.35 } });  // raw reports sit under the merged incidents
      m.addLayer({ id: "incidents", type: "circle", source: "incidents",  // solid = verified, hollow = unverified
        paint: { "circle-radius": ["match", ["get", "kind"], ["downed_line", "substation_damage", "outage", "tree_on_line"], 7, 4],  // grid damage stands out
          "circle-color": ["case", ["boolean", ["get", "verified"], false], incidentColor, "#ffffff"],
          "circle-stroke-color": incidentColor, "circle-stroke-width": 2.5, "circle-opacity": 0.9 } });
      m.on("click", "incidents", (e) => incidentRef.current?.(Number(e.features![0].properties.id)));
      m.on("mouseenter", "incidents", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "incidents", () => (m.getCanvas().style.cursor = ""));
      m.addLayer({ id: "staging", type: "circle", source: "staging",
        paint: { "circle-radius": 13, "circle-color": "#12a36b", "circle-stroke-color": "#fff", "circle-stroke-width": 4 } });
      m.addLayer({ id: "staging-label", type: "symbol", source: "staging",
        layout: { "text-field": "Shared staging", "text-size": 13, "text-offset": [0, 1.8], "text-font": ["Montserrat Medium"] },
        paint: { "text-color": "#0b7a4f", "text-halo-color": "#fff", "text-halo-width": 2 } });
      m.on("click", "reports", (e) => {
        const p = JSON.parse(String(e.features![0].properties.payload));
        new maplibregl.Popup({ closeButton: false, maxWidth: "300px" }).setLngLat(e.lngLat)
          .setHTML(`<b>${esc(p.type ?? p.kind)} · ${esc(p.place)}, ${esc(p.state)}</b><br/>${esc(p.remark ?? p.comments)}`).addTo(m);
      });
      m.addLayer({ id: "opp-selected", type: "circle", source: "opps", filter: ["all", ["has", "marker"], ["==", ["get", "id"], -1]],
        paint: { "circle-radius": 21, "circle-color": "transparent", "circle-stroke-color": "#1b2447", "circle-stroke-width": 3 } });
      m.addLayer({ id: "job-hover-line", type: "line", source: "jobs", filter: ["==", ROW_KEY, ""],
        layout: { "line-cap": "round" }, paint: { "line-color": "#f59e0b", "line-width": 8, "line-opacity": 0.55 } });
      m.addLayer({ id: "job-hover-point", type: "circle", source: "jobs", filter: ["all", ["==", ["geometry-type"], "Point"], ["==", ROW_KEY, ""]],
        paint: { "circle-radius": 10, "circle-color": "transparent", "circle-stroke-color": "#f59e0b", "circle-stroke-width": 3.5 } });

      m.on("click", (e) => clickRef.current?.(e.lngLat.lng, e.lngLat.lat));
      m.on("click", "opp-markers", (e) => {
        if (clickRef.current) return;
        const p = e.features![0].properties;
        const ids = String(p.ids).split(",").filter(Boolean).map(Number);
        if (ids.length === 1) return onSelectRef.current(ids[0]);
        new maplibregl.Popup({ closeButton: false, maxWidth: "340px" }).setLngLat(e.lngLat).setDOMContent(pickList(ids, oppsRef.current, (id) => onSelectRef.current(id))).addTo(m);
      });
      for (const layer of ["job-hit", "job-points"]) {
        m.on("click", layer, (e) => {
          if (clickRef.current || m.queryRenderedFeatures(e.point, { layers: ["opp-markers"] }).length) return;  // markers win
          new maplibregl.Popup({ closeButton: false, maxWidth: "300px" }).setLngLat(e.lngLat).setHTML(jobPopup(e.features![0].properties)).addTo(m);
        });
      }
      for (const layer of ["opp-markers", "job-hit", "job-points"]) {
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      }
      let hovered: string | null = null;
      for (const layer of ["job-hit", "job-points"]) {
        m.on("mousemove", layer, (e) => {
          const p = e.features![0].properties;
          const key = p.parent_job_id && p.parent_job_id !== "null" ? String(p.parent_job_id) : String(p.id);
          if (key !== hovered) hoverRef.current((hovered = key));  // only report changes
        });
        m.on("mouseleave", layer, () => { hovered = null; hoverRef.current(null); });
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
    const inGroup = ["in", `,${selected?.id ?? -1},`, ["coalesce", ["get", "ids"], ""]] as maplibregl.ExpressionSpecification;  // marker holds every pair at its spot
    m.setFilter("opp-selected", ["all", ["has", "marker"], inGroup]);
    const focus = (on: number, off: number) =>
      (selected ? ["case", ["any", ["==", ["get", "id"], selected.id], inGroup], on, off] : on) as maplibregl.ExpressionSpecification;
    m.setPaintProperty("opp-links", "line-opacity", focus(0.95, 0.2));
    m.setPaintProperty("opp-markers", "circle-stroke-opacity", focus(1, 0.4));
    m.setPaintProperty("opp-markers", "circle-opacity", focus(1, 0.35));
    m.setPaintProperty("opp-glow", "circle-opacity", focus(0.3, 0.05));
    if (!selected) return;
    m.resize(); // detail panel may have just narrowed the map
    const coords = jobs.features.filter((f) => ids.includes(String(f.id))).flatMap((f) => coordsOf(f.geometry));
    if (coords.length) m.fitBounds(bounds(coords), { padding: { top: 90, bottom: 90, left: 90, right: 500 }, maxZoom: 11, duration: 900 });  // room for the detail sheet
  }, [selected, jobs, loaded]);

  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;
    if ((layers.risk || layers.vulnerability) && !tractsLoaded.current) {
      tractsLoaded.current = true;
      api.tracts().then((d) => (m.getSource("tracts") as GeoJSONSource).setData(d));
    }
    if (layers.grid && !gridLoaded.current) {
      gridLoaded.current = true;
      api.grid().then((d) => (m.getSource("grid") as GeoJSONSource).setData(d));
    }
    m.setLayoutProperty("grid", "visibility", layers.grid ? "visible" : "none");
    m.setLayoutProperty("tract-risk", "visibility", layers.risk ? "visible" : "none");
    m.setLayoutProperty("tract-vulnerability", "visibility", layers.vulnerability ? "visible" : "none");
  }, [layers, loaded]);

  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;
    for (const key of ["cone", "track", "warnings", "reports", "staging", "incidents"] as const) {
      (m.getSource(key) as GeoJSONSource).setData(storm ? storm[key] : EMPTY);
    }
  }, [storm, loaded]);

  useEffect(() => {
    if (map.current) map.current.getCanvas().style.cursor = onMapClick ? "crosshair" : "";
  }, [onMapClick]);

  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;
    m.setFilter("job-hover-line", ["==", ROW_KEY, hoverKey ?? ""]);
    m.setFilter("job-hover-point", ["all", ["==", ["geometry-type"], "Point"], ["==", ROW_KEY, hoverKey ?? ""]]);
  }, [hoverKey, loaded]);

  useEffect(() => {
    const m = map.current;
    if (!m || !loaded) return;
    (m.getSource("zone") as GeoJSONSource).setData(zone ?? EMPTY);
  }, [zone, loaded]);

  useEffect(() => {
    if (!fly || !map.current) return;
    const [x0, y0, x1, y1] = fly.bbox;
    map.current.fitBounds([[x0, y0], [x1, y1]], { padding: 40, duration: 900 });
  }, [fly]);

  return (
    <div className="relative h-full w-full">
      <div ref={box} className="h-full w-full" />
      <OrgKey jobs={jobs} />
      <LayersMenu layers={layers} onToggle={(key) => setLayers((l) => ({ ...l, [key]: !l[key] }))} storm={!!storm} />
    </div>
  );
}

function OrgKey({ jobs }: { jobs: JobCollection | null }) {
  const orgs = new Map<string, string>();
  jobs?.features.forEach((f) => orgs.set(f.properties.org_name, f.properties.color));
  return (
    <div className="absolute left-4 top-4 flex flex-wrap gap-2">
      {[...orgs].map(([name, color]) => (
        <span key={name} className="inline-flex items-center gap-2 rounded-full bg-surface/95 px-3 py-1.5 text-[13px] font-semibold shadow-float">
          <span className="h-3 w-3 rounded-full ring-4" style={{ background: color, ["--tw-ring-color" as string]: color === DESC_COLOR ? "#e5edff" : color === GPC_COLOR ? "#ffe8e8" : "#eef1f7" }} />{name}
        </span>
      ))}
    </div>
  );
}

type LayerKey = "grid" | "risk" | "vulnerability";

function LayersMenu({ layers, onToggle, storm }: { layers: Record<LayerKey, boolean>; onToggle: (k: LayerKey) => void; storm: boolean }) {
  const [open, setOpen] = useState(false);
  const toggles: [LayerKey, string, string][] = [["grid", "Existing power lines", "Every mapped transmission line"],
    ["risk", "Hurricane risk", "FEMA risk by census tract"], ["vulnerability", "Community vulnerability", "CDC social vulnerability"]];
  return (
    <div className="absolute right-16 top-4">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-full bg-surface px-4 py-2 text-[14px] font-semibold shadow-float hover:bg-soft">
        <Layers size={16} /> Layers and key
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-[320px] rounded-[var(--radius-bubble)] bg-surface p-4 shadow-float">
          <div className="flex items-center justify-between"><span className="display text-[16px] font-semibold">Map layers</span>
            <button aria-label="Close" onClick={() => setOpen(false)} className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-soft"><X size={16} /></button></div>
          <div className="mt-2 space-y-1">
            {toggles.map(([key, label, hint]) => (
              <label key={key} className="flex cursor-pointer items-center justify-between rounded-2xl px-2 py-2 hover:bg-soft">
                <span><span className="block text-[14px] font-semibold">{label}</span><span className="block text-[12px] text-muted">{hint}</span></span>
                <input type="checkbox" checked={layers[key]} onChange={() => onToggle(key)} className="h-5 w-5 accent-[#2f6bff]" />
              </label>
            ))}
          </div>
          <div className="display mt-4 text-[16px] font-semibold">What the colors mean</div>
          {storm ? (
            <div className="mt-2 space-y-1.5 text-[13px] text-muted">
              <KeyRow swatch={<span className="h-3 w-6 rounded-sm border-2 border-dashed border-rose-500 bg-rose-500/10" />}>Forecast cone</KeyRow>
              <KeyRow swatch={<span className="h-1.5 w-6 rounded bg-rose-900" />}>Storm track</KeyRow>
              <KeyRow swatch={<span className="h-3.5 w-3.5 rounded-full border-2 border-red-600 bg-red-600" />}>Verified incident</KeyRow>
              <KeyRow swatch={<span className="h-3.5 w-3.5 rounded-full border-2 border-red-600 bg-white" />}>News only, not confirmed</KeyRow>
              <KeyRow swatch={<span className="h-2 w-2 rounded-full bg-slate-400" />}>Damage report</KeyRow>
              <KeyRow swatch={<span className="h-4 w-4 rounded-full border-2 border-white bg-save shadow" />}>Shared staging point</KeyRow>
            </div>
          ) : (
            <div className="mt-2 space-y-1.5 text-[13px] text-muted">
              {Object.entries(TIER_LABEL).map(([tier, label]) => (
                <KeyRow key={tier} swatch={<span className="h-4 w-4 rounded-full border-[3px] border-white shadow" style={{ background: TIER_COLOR[tier as keyof typeof TIER_COLOR] }} />}>{label}</KeyRow>
              ))}
              <KeyRow swatch={<span className="h-4 w-4 rounded-full border-[3px] border-white shadow" style={{ background: FAR_COLOR }} />}>Too far by road (over 45 min)</KeyRow>
              <KeyRow swatch={<span className="w-6 border-t-[3px] border-dashed border-slate-400" />}>Route not mapped yet, drawn straight</KeyRow>
              <KeyRow swatch={<span className="h-3.5 w-3.5 rounded-full border-[3px] border-slate-400 bg-white" />}>Only one end located</KeyRow>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function KeyRow({ swatch, children }: { swatch: React.ReactNode; children: React.ReactNode }) {
  return <div className="flex items-center gap-3"><span className="grid w-6 place-items-center">{swatch}</span>{children}</div>;
}
