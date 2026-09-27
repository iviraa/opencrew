import { useCallback, useMemo, useState } from "react";
import { colorFor, type ChatAction, type Jobs, type Me, type Overlap } from "../data";
import { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { say } from "../mascot";
import type { CardProps } from "./Cards";
import type { HazardControl, MapCard, MapView, Route, Timeline } from "./types";

const CARD_TYPES = new Set(["projects", "timeline", "forecast", "route", "download", "share", "explain"]);
const GRAPE = "#5b2bb5";

type Deps = {
  me: Me | null; projects: Jobs | null; ov: { overlaps: Overlap[]; jobs: Jobs } | null;
  setTab: (t: "overlaps" | "weather" | "news") => void; setFit: (f: Fit) => void; showIds: (ids: number[]) => Promise<void>; setPartner: (p: string | null) => void;
  pickProject: (id: string) => void; openOverlap: (id: number) => void; setOthers: (on: boolean) => void;
};

// the chat's map, data and explain hand-overs: applies map_view, keeps the highlight, route and timeline the map draws, and makes the cards
export function useMapTools({ me, projects, ov, setTab, setFit, showIds, setPartner, pickProject, openOverlap, setOthers }: Deps) {
  const [highlight, setHighlight] = useState<Set<string> | null>(null);  // project ids a filter picked
  const [route, setRoute] = useState<Route | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [hazardControl, setHazardControl] = useState<HazardControl | null>(null);

  const fitProjects = useCallback((ids: Set<string>) => {
    const feats = projects?.features.filter((f) => ids.has(f.properties.id)) ?? [];
    const b = bboxOf([{ type: "FeatureCollection", features: feats }]);
    if (b) setFit({ bbox: b, key: `h${Date.now()}`, maxZoom: 10 });
  }, [projects, setFit]);

  const showRoute = useCallback((r: Route) => {
    setRoute(r); setTab("overlaps"); setTimeline(null);
    const b = bboxOf([{ type: "FeatureCollection", features: [{ type: "Feature", geometry: r.geometry, properties: {} }] }]);
    if (b) setFit({ bbox: b, key: `r${Date.now()}`, maxZoom: 11 });
  }, [setFit, setTab]);

  const applyView = useCallback(async (v: MapView) => {
    if (v.layers?.others != null) setOthers(v.layers.others);
    if (v.tab === "hazards") { setTab("weather"); setHazardControl({ period: v.period, month: v.month, hazards: v.hazards, at: Date.now() }); return; }
    if (v.tab === "news") { setTab("news"); return; }
    setTab("overlaps"); setTimeline(null);
    if (v.partner) setPartner(v.partner);  // the ids themselves ride in the message like any overlap list
    const fit = v.fit;
    if (!fit) return;
    if ("bbox" in fit) setFit({ bbox: fit.bbox, key: `v${Date.now()}` });
    else if (fit.to === "ours") { const b = bboxOf([projects ?? undefined]); if (b) setFit({ bbox: b, key: `v${Date.now()}` }); }
    else if (fit.to === "overlaps") { const b = bboxOf([ov?.jobs]); if (b) setFit({ bbox: b, key: `v${Date.now()}` }); }
    else if (fit.to.startsWith("overlap:")) await showIds([Number(fit.to.slice(8))]);
  }, [projects, ov, setTab, setFit, showIds, setPartner, setOthers]);

  const cardsOf = useCallback((actions: ChatAction[]) => actions.filter((a) => CARD_TYPES.has(a.type)) as unknown as MapCard[], []);

  // side effects for one reply's ui_actions, after the shell has shown any overlap ids
  const apply = useCallback(async (actions: ChatAction[]) => {
    const cards = cardsOf(actions);
    for (const a of actions) if (a.type === "map_view") await applyView(a as unknown as MapView);
    const p = cards.filter((c) => c.type === "projects").pop();
    if (p?.type === "projects") { const ids = new Set(p.projects.rows.map((r) => r.id)); setHighlight(ids); setTab("overlaps"); setTimeline(null); fitProjects(ids); }
    const t = cards.filter((c) => c.type === "timeline").pop();
    if (t?.type === "timeline") { setTab("overlaps"); setTimeline(t.timeline); }
    const r = cards.filter((c) => c.type === "route").pop();
    if (r?.type === "route") showRoute(r.route);
  }, [cardsOf, applyView, fitProjects, showRoute, setTab]);

  const line = useCallback((cards: MapCard[]) => {  // what the beaver says for these cards
    const c = cards[cards.length - 1];
    if (!c) return null;
    switch (c.type) {
      case "projects": return `${c.projects.rows.length} projects are highlighted on the map.`;
      case "timeline": return `Here are ${c.timeline.rows.length} build windows on the calendar.`;
      case "forecast": return c.forecast.days.some((d) => d.notes.length) ? "Some days there carry a weather note." : "A quiet week at that site.";
      case "route": return c.route.drive_min != null ? `About ${Math.round(c.route.drive_min)} minutes by road.` : "I drew the straight line; the router was quiet.";
      case "download": return "Your file is ready to save.";
      case "share": return "Here's a link you can pass along.";
      case "explain": return "Here's how that number was made.";
      default: return null;
    }
  }, []);

  // the highlight and route drawn over whatever the map shows
  const decorate = useCallback((scene: Scene): Scene => {
    if (!highlight && !route) return scene;
    const lines = [...(scene.lines?.features ?? [])], points = [...(scene.points?.features ?? [])];
    if (highlight && me) {
      const color = colorFor(me.company);
      const dim = (f: GeoJSON.Feature) => ({ ...f, properties: { ...f.properties, opacity: 0.15 } });
      const base = { lines: lines.map(dim), points: points.map(dim) };
      lines.length = 0; points.length = 0; lines.push(...base.lines); points.push(...base.points);
      projects?.features.filter((f) => highlight.has(f.properties.id)).forEach((f) => {
        const props = { color, width: 5, radius: 7, stroke: "#111014", opacity: 1, title: `<b>${esc(f.properties.name)}</b><br/>${esc(me.name)}`, pick: `job:${f.properties.id}` };
        (f.geometry.type === "Point" ? points : lines).push({ type: "Feature", geometry: f.geometry, properties: props });
      });
    }
    if (route) {
      const title = `<b>${esc(route.from)} → ${esc(route.to)}</b><br/>${route.drive_min != null ? `${route.road_mi} mi · ${Math.round(route.drive_min)} min` : `${route.straight_mi} mi straight`}`;
      lines.push({ type: "Feature", geometry: route.geometry, properties: { color: GRAPE, width: 4, opacity: 0.9, title } });
      points.push({ type: "Feature", geometry: { type: "Point", coordinates: route.a }, properties: { color: GRAPE, radius: 7, stroke: "#ffffff", title: `<b>${esc(route.from)}</b>` } },
        { type: "Feature", geometry: { type: "Point", coordinates: route.b }, properties: { color: "#111014", radius: 7, stroke: "#ffffff", title: `<b>${esc(route.to)}</b>` } });
    }
    return { ...scene, lines: { type: "FeatureCollection", features: lines }, points: { type: "FeatureCollection", features: points } };
  }, [highlight, route, projects, me]);

  const clear = useCallback(() => { setHighlight(null); setRoute(null); }, []);
  const cardProps = useMemo<CardProps>(() => ({
    onPickProject: (id, mine) => { setTab("overlaps"); setTimeline(null); if (mine !== false) pickProject(id); else say("That one is the neighbor's; I only fly to ours.", "nod"); },
    onOpenTimeline: (t) => { setTab("overlaps"); setTimeline(t); },
    onShowRoute: showRoute,
    onOpen: openOverlap,
  }), [pickProject, openOverlap, showRoute, setTab]);

  return { cardsOf, apply, line, decorate, timeline, closeTimeline: () => setTimeline(null), hazardControl, cardProps, decorated: !!(highlight || route), clear };
}
