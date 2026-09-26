import { CloudLightning, Droplets, ExternalLink, Newspaper, ShieldCheck, Tornado, Wind, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { NewsPin } from "../api";
import type { HeadsUp, OutlookFrame } from "../api-outlook";
import { riskColor } from "../api-outlook";
import { ago, publicApi, type Jobs } from "./data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "./MapPane";
import { PanelHeader } from "./panels";

export type Scenario = "now" | "helene";
const HELENE_WEATHER = "2024-09-25T12:00:00Z";  // two days before landfall: outlooks are lit up
const HELENE_NEWS = "2024-09-27T12:00:00Z";  // the morning after landfall: damage reports pour in

export function Split({ map, side }: { map: React.ReactNode; side: React.ReactNode }) {
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,3fr)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] gap-5">
      <div className="min-h-0">{map}</div>
      <aside className="slide-in flex min-h-0 min-w-0 flex-col">{side}</aside>
    </div>
  );
}

function ScenarioSwitch({ value, onChange }: { value: Scenario; onChange: (s: Scenario) => void }) {
  return (
    <div className="mb-3 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
      {([["now", "Right now"], ["helene", "Helene 2024 replay"]] as const).map(([k, label]) => (
        <button key={k} onClick={() => onChange(k)} className={`flex-1 rounded-full py-1 ${value === k ? "bg-white shadow-sm" : "text-muted"}`}>{label}</button>
      ))}
    </div>
  );
}

// our projects as quiet grey context under weather and news
function context(projects: Jobs | null): GeoJSON.Feature[] {
  return (projects?.features ?? []).map((f) => ({ ...f, properties: { color: "#8a94b0", width: 2, opacity: 0.55, radius: 3, title: esc(f.properties.name) } }));
}

const splitGeoms = (fs: GeoJSON.Feature[]) => ({
  lines: fs.filter((f) => f.geometry?.type !== "Point"),
  points: fs.filter((f) => f.geometry?.type === "Point"),
});

const HEADS_ICON: Record<string, typeof Wind> = { severe: CloudLightning, severe48: CloudLightning, flood: Droplets, tropical: Tornado, wind: Wind, watch: Zap };

export function WeatherTab({ projects, side }: { projects: Jobs | null; side: React.ReactNode | null }) {
  const [scenario, setScenario] = useState<Scenario>("now");
  const [frame, setFrame] = useState<OutlookFrame | null>(null);
  const [alerts, setAlerts] = useState<GeoJSON.FeatureCollection | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setFrame(null); setErr(null);
    const q = scenario === "now" ? "scenario=none" : `scenario=helene&at=${HELENE_WEATHER}`;
    publicApi.get<OutlookFrame>(`/api/outlook/frame?${q}`).then(setFrame).catch((e) => setErr(String(e)));
    if (scenario === "now") publicApi.get<GeoJSON.FeatureCollection>("/api/weather/alerts").then(setAlerts).catch(() => setAlerts(null));
    else setAlerts(null);
  }, [scenario]);

  const scene = useMemo<Scene>(() => {
    const areas: GeoJSON.Feature[] = (frame?.outlooks.features ?? []).map((f) => ({
      ...f, properties: { color: riskColor(f.properties.rank), opacity: 0.12 + f.properties.rank * 0.05, title: `<b>${esc(f.properties.label)}</b><br/>${esc(f.properties.level)}` },
    }));
    (alerts?.features ?? []).forEach((f) => areas.push({ ...f, properties: { color: "#c9184a", opacity: 0.3, title: esc((f.properties as { event?: string })?.event ?? "Weather alert") } }));
    const ctx = splitGeoms(context(projects));
    return { areas: { type: "FeatureCollection", features: areas }, lines: { type: "FeatureCollection", features: ctx.lines }, points: { type: "FeatureCollection", features: ctx.points } };
  }, [frame, alerts, projects]);

  const pick = (h: HeadsUp) => h.bbox && setFit({ bbox: h.bbox, key: h.id + Date.now(), maxZoom: 8 });
  const heads = frame?.heads_up ?? [];

  return (
    <Split map={<MapPane scene={scene} fit={fit} />} side={side ?? (
      <>
        <PanelHeader title="Weather outlook" sub={scenario === "now" ? "Official forecasts for the next 7 days" : "Sept 25, 2024, two days before Helene"} />
        <ScenarioSwitch value={scenario} onChange={setScenario} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1.5 overflow-y-auto pr-2">
          {!frame && !err && <p className="text-sm text-muted"><span className="dots">Checking forecasts</span></p>}
          {err && <p className="text-sm text-warn">{err}</p>}
          {frame && !heads.length && (
            <div className="rounded-2xl bg-save-soft/70 px-3 py-3 text-sm">
              <div className="flex items-center gap-1.5 font-semibold text-save"><ShieldCheck size={16} /> All clear</div>
              <p className="mt-1 text-muted">No severe storm, flash flood or tropical outlook touches your work areas this week{alerts?.features.length ? `, and ${alerts.features.length} active alert${alerts.features.length === 1 ? " is" : "s are"} shown on the map` : ""}.</p>
              <button onClick={() => setScenario("helene")} className="mt-2 text-xs font-semibold text-grape underline">See what a storm week looks like</button>
            </div>
          )}
          {heads.map((h) => {
            const Icon = HEADS_ICON[h.kind] ?? CloudLightning;
            return (
              <button key={h.id} onClick={() => pick(h)} className="flex gap-2.5 rounded-2xl px-2 py-2 text-left hover:bg-soft">
                <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full text-white" style={{ background: riskColor(h.rank) }}><Icon size={16} /></span>
                <span className="min-w-0">
                  <span className="text-xs font-semibold text-muted">{h.day} · {h.level}</span>
                  <span className="block text-sm leading-snug">{h.text}</span>
                </span>
              </button>
            );
          })}
        </div>
      </>
    )} />
  );
}

type Incident = { id: number; ts: string; kind: string; where_text: string; verified: boolean; confidence: number; n_sources: number; customers_affected: number | null };
type IncidentDetail = Incident & { sources: { type: string; name: string; url?: string; title?: string; quote_evidence?: string }[] };
type LiveFrame = { incidents: GeoJSON.FeatureCollection<GeoJSON.Point, Incident>; news: GeoJSON.FeatureCollection<GeoJSON.Point, NewsPin> };

const KIND_COLOR: Record<string, string> = { outage: "#ff7a3d", downed_line: "#e8590c", substation_damage: "#c9184a", flooding: "#2f6bff", tree_down: "#12a36b" };
const kindColor = (k: string) => KIND_COLOR[k] ?? "#ff4f5e";
const kindLabel = (k: string) => k.replace(/_/g, " ");

export function NewsTab({ projects, side }: { projects: Jobs | null; side: React.ReactNode | null }) {
  const [scenario, setScenario] = useState<Scenario>("now");
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [open, setOpen] = useState<IncidentDetail | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setFrame(null); setOpen(null); setErr(null);
    const q = scenario === "now" ? "scenario=none" : `scenario=helene&at=${HELENE_NEWS}`;
    publicApi.get<LiveFrame>(`/api/live/frame?${q}`).then((f) => {
      setFrame(f);
      const b = bboxOf([f.incidents, f.news]);
      if (b) setFit({ bbox: b, key: scenario + Date.now(), maxZoom: 9 });
    }).catch((e) => setErr(String(e)));
  }, [scenario]);

  const incidents = useMemo(() => (frame?.incidents.features ?? []).map((f) => ({ ...f.properties, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] }))
    .sort((a, b) => Number(b.verified) - Number(a.verified) || b.confidence - a.confidence), [frame]);
  const news = useMemo(() => frame?.news.features ?? [], [frame]);

  const scene = useMemo<Scene>(() => {
    const ctx = splitGeoms(context(projects));
    const pts: GeoJSON.Feature[] = [
      ...ctx.points,
      ...(frame?.incidents.features ?? []).map((f) => ({ ...f, properties: {
        color: kindColor(f.properties.kind), radius: f.properties.verified ? 6 : 4.5, opacity: open && open.id !== f.properties.id ? 0.35 : 1,
        title: `<b>${esc(kindLabel(f.properties.kind))}</b><br/>${esc(f.properties.where_text)}`, pick: `inc:${f.properties.id}` } })),
      ...news.map((f, i) => ({ ...f, properties: { color: "#5b2bb5", radius: 8, stroke: "#111014",
        title: `<b>${esc(f.properties.articles[0]?.title ?? "News")}</b><br/>near ${esc(f.properties.near_name)}`, pick: `news:${i}` } })),
    ];
    return { lines: { type: "FeatureCollection", features: ctx.lines }, points: { type: "FeatureCollection", features: pts } };
  }, [frame, projects, open, news]);

  const openIncident = (id: number) => {
    const inc = incidents.find((x) => x.id === id);
    if (inc) setFit({ bbox: [inc.lon - 0.15, inc.lat - 0.1, inc.lon + 0.15, inc.lat + 0.1], key: `i${id}${Date.now()}`, maxZoom: 10 });
    publicApi.get<IncidentDetail>(`/api/incidents/${id}`).then(setOpen).catch(() => {});
  };
  const onPick = (p: string) => { if (p.startsWith("inc:")) openIncident(Number(p.slice(4))); };

  return (
    <Split map={<MapPane scene={scene} fit={fit} onPick={onPick} />} side={side ?? (open ? (
      <>
        <PanelHeader title={kindLabel(open.kind)} sub={`${open.where_text} · ${ago(open.ts)}`} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
          <div className="flex flex-wrap gap-1.5 text-xs font-semibold">
            <span className={`rounded-full px-2 py-0.5 ${open.verified ? "bg-save-soft text-save" : "bg-crew-soft text-[#8a5a00]"}`}>{open.verified ? "Verified" : "Unconfirmed"}</span>
            <span className="rounded-full bg-soft px-2 py-0.5">{Math.round(open.confidence * 100)}% confidence</span>
            {open.customers_affected != null && <span className="rounded-full bg-soft px-2 py-0.5">{open.customers_affected.toLocaleString()} customers</span>}
          </div>
          <h3 className="mt-1 text-sm font-semibold text-muted">Sources</h3>
          {open.sources.map((s, i) => (
            <div key={i} className="rounded-xl border-2 border-line px-2.5 py-2 text-sm">
              <div className="text-xs font-semibold text-muted">{s.name}</div>
              {s.title && <div className="font-semibold leading-snug">{s.title}</div>}
              {s.quote_evidence && <p className="mt-0.5 text-xs italic text-muted">"{s.quote_evidence}"</p>}
              {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Open <ExternalLink size={11} /></a>}
            </div>
          ))}
        </div>
      </>
    ) : (
      <>
        <PanelHeader title="News & damage" sub={scenario === "now" ? "Reports from the last few days" : "Sept 27, 2024, the morning after Helene"} />
        <ScenarioSwitch value={scenario} onChange={setScenario} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1 overflow-y-auto pr-2">
          {!frame && !err && <p className="text-sm text-muted"><span className="dots">Reading the news</span></p>}
          {err && <p className="text-sm text-warn">{err}</p>}
          {news.length > 0 && <h3 className="mt-1 flex items-center gap-1.5 px-2 text-xs font-semibold uppercase tracking-wide text-faint"><Newspaper size={13} /> In the news</h3>}
          {news.slice(0, 12).map((f, i) => {
            const a = f.properties.articles[0];
            const [lon, lat] = f.geometry.coordinates;
            return (
              <div key={i} className="rounded-2xl px-2 py-2 hover:bg-soft">
                <button onClick={() => setFit({ bbox: [lon - 0.15, lat - 0.1, lon + 0.15, lat + 0.1], key: `n${i}${Date.now()}`, maxZoom: 10 })} className="text-left">
                  <span className="text-xs text-muted">{a?.source} · near {f.properties.near_name}</span>
                  <span className="line-clamp-2 block text-sm font-semibold leading-snug">{a?.title}</span>
                </button>
                {a?.url && <a href={a.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Read <ExternalLink size={11} /></a>}
              </div>
            );
          })}
          {incidents.length > 0 && <h3 className="mt-2 px-2 text-xs font-semibold uppercase tracking-wide text-faint">Damage reports · {incidents.length}</h3>}
          {incidents.slice(0, 80).map((x) => (
            <button key={x.id} onClick={() => openIncident(x.id)} className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
              <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: kindColor(x.kind) }} />
              <span className="min-w-0">
                <span className="block text-sm font-semibold capitalize leading-snug">{kindLabel(x.kind)}</span>
                <span className="block text-xs text-muted">{x.where_text} · {ago(x.ts)}{x.verified ? " · verified" : ""}</span>
              </span>
            </button>
          ))}
          {frame && !incidents.length && !news.length && <p className="px-2 py-6 text-center text-sm text-muted">No damage reports right now.</p>}
        </div>
      </>
    ))} />
  );
}
