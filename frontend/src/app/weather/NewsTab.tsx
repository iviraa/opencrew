import { AlertTriangle, ExternalLink, HardHat, MapPin, Newspaper } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { say, type Mood } from "../mascot";
import type { NewsPin } from "../../api";
import { ago, api, publicApi, type Jobs } from "../data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { PanelHeader } from "../panels";
import { ScenarioSwitch, SectionTitle, Split, around, fc, nearestProject, splitGeoms, when, type Scenario } from "./shared";

const HELENE_NEWS = "2024-09-27T12:00:00Z";  // the morning after landfall: damage reports pour in

type Incident = { id: number; ts: string; kind: string; where_text: string; verified: boolean; confidence: number; n_sources: number; customers_affected: number | null };
type Source = { type: string; name: string; url?: string; title?: string; quote_evidence?: string; ts?: string };
type IncidentDetail = Incident & { lat: number; lon: number; sources: Source[] };
type LiveFrame = { incidents: GeoJSON.FeatureCollection<GeoJSON.Point, Incident>; news: GeoJSON.FeatureCollection<GeoJSON.Point, NewsPin> };
type Open = { kind: "incident"; detail: IncidentDetail } | { kind: "news"; idx: number } | { kind: "story"; item: Story } | null;

// a story the news pipeline linked to us or a neighbor (see backend/app/news)
type Story = {
  id: number; title: string; source: string | null; url: string; published: string | null; impact: string; affects_work: boolean; summary: string | null;
  confidence: number; org_ids: string[]; job_ids: string[]; opportunity_ids: number[]; verified: boolean; mine: boolean; direct: boolean; about: string[];
  evidence: { org?: string[]; station?: string[]; county?: string[]; keyword?: string; verified_by?: Record<string, string>; provider?: string };
};
type NewsFeed = { items: Story[]; partners: string[]; impacts: string[] };

const IMPACT: Record<string, { label: string; color: string }> = {
  delay: { label: "Delay", color: "#ff9f1c" }, damage: { label: "Damage", color: "#c9184a" }, outage: { label: "Outage", color: "#1b2447" },
  opposition: { label: "Opposition", color: "#e84393" }, regulatory: { label: "Regulatory", color: "#3a86ff" }, supply_chain: { label: "Supply chain", color: "#8e5cf7" },
  security: { label: "Security", color: "#ef476f" }, funding: { label: "Funding", color: "#12a36b" }, construction: { label: "Construction", color: "#00b8a9" },
  other: { label: "Other", color: "#8a94b0" },
};
const impactOf = (k: string) => IMPACT[k] ?? IMPACT.other;

const KIND: Record<string, { label: string; color: string }> = {
  wind_damage: { label: "Wind damage", color: "#ff9f1c" },
  tornado: { label: "Tornado", color: "#c9184a" },
  downed_line: { label: "Downed line", color: "#7c4dff" },
  tree_on_line: { label: "Tree on line", color: "#12a36b" },
  flooding: { label: "Flooding", color: "#2f6bff" },
  outage: { label: "Outage", color: "#1b2447" },
};
const kindOf = (k: string) => KIND[k] ?? { label: k.replace(/_/g, " "), color: "#ff4f5e" };
const NEWS_COLOR = "#5b2bb5";

function Near({ projects, lon, lat }: { projects: Jobs | null; lon: number; lat: number }) {
  const n = useMemo(() => nearestProject(projects, lon, lat), [projects, lon, lat]);
  if (!n) return null;
  return (
    <div className="flex items-center gap-2 rounded-xl bg-soft px-2.5 py-2 text-sm">
      <HardHat size={15} className="shrink-0 text-muted" />
      <span className="min-w-0"><span className="text-muted">Nearest of your projects: </span><b>{n.name}</b> · {n.mi < 1 ? n.mi.toFixed(1) : Math.round(n.mi)} mi</span>
    </div>
  );
}

// one short line for the beaver about damage reports
function newsLine(f: LiveFrame): [string, Mood] {
  const n = f.incidents.features.length, v = f.incidents.features.filter((x) => x.properties.verified).length, a = f.news.features.length;
  if (!n && !a) return ["No damage reports right now. All quiet!", "happy"];
  if (!n) return [`${a} news story${a === 1 ? "" : "s"} near our area, no damage reports.`, "nod"];
  return [`${n} damage report${n === 1 ? "" : "s"} found, ${v} verified.`, "surprised"];
}

export default function NewsTab({ projects, side, onOpenOverlap }: { projects: Jobs | null; side: React.ReactNode | null; onOpenOverlap?: (id: number) => void }) {
  const [scenario, setScenario] = useState<Scenario>("now");
  const [stories, setStories] = useState<Story[] | null>(null);
  const [impact, setImpact] = useState<string | null>(null);

  useEffect(() => { api.get<NewsFeed>("/api/app/news?days=90").then((f) => setStories(f.items)).catch(() => setStories([])); }, []);
  const forUs = useMemo(() => (stories ?? []).filter((s) => !impact || s.impact === impact), [stories, impact]);
  const impacts = useMemo(() => {
    const n = new Map<string, number>();
    (stories ?? []).forEach((s) => n.set(s.impact, (n.get(s.impact) ?? 0) + 1));
    return [...n.entries()].sort((a, b) => b[1] - a[1]);
  }, [stories]);
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());  // kinds switched off in the legend
  const [fit, setFit] = useState<Fit | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const replay = scenario === "helene";

  useEffect(() => {
    setFrame(null); setOpen(null); setErr(null); setHidden(new Set());
    say(replay ? "Pulling up reports from Helene..." : "Reading the latest news...", "thinking");
    const q = replay ? `scenario=helene&at=${HELENE_NEWS}` : "scenario=none";
    publicApi.get<LiveFrame>(`/api/live/frame?${q}`).then((f) => {
      setFrame(f);
      say(...newsLine(f));
      const b = bboxOf([f.incidents, f.news]);
      if (b) setFit({ bbox: b, key: scenario + Date.now(), maxZoom: 9 });
    }).catch((e) => { setErr(String(e)); say("I couldn't load the news.", "sad"); });
  }, [scenario, replay]);

  const all = useMemo(() => (frame?.incidents.features ?? []).map((f) => ({ ...f.properties, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] }))
    .sort((a, b) => Number(b.verified) - Number(a.verified) || Date.parse(b.ts) - Date.parse(a.ts)), [frame]);
  const incidents = useMemo(() => all.filter((x) => !hidden.has(x.kind)), [all, hidden]);
  const kinds = useMemo(() => [...new Set(all.map((x) => x.kind))].map((k) => ({ k, n: all.filter((x) => x.kind === k).length })).sort((a, b) => b.n - a.n), [all]);
  const news = useMemo(() => frame?.news.features ?? [], [frame]);
  const openId = open?.kind === "incident" ? open.detail.id : null;

  const scene = useMemo<Scene>(() => {
    const ours = (projects?.features ?? []).map((f) => ({ ...f, properties: { color: "#8a94b0", width: 2, opacity: 0.5, radius: 3, title: esc(f.properties.name) } }));
    const g = splitGeoms(ours);
    const pts: GeoJSON.Feature[] = [
      ...g.points,
      ...incidents.map((x) => ({ type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [x.lon, x.lat] }, properties: {
        color: kindOf(x.kind).color, radius: openId === x.id ? 9 : x.verified ? 5.5 : 4, opacity: openId && openId !== x.id ? 0.3 : x.verified ? 0.95 : 0.55,
        stroke: openId === x.id ? "#111014" : "#ffffff",
        title: `<b>${esc(kindOf(x.kind).label)}</b>${x.verified ? "" : " (unconfirmed)"}<br/>${esc(x.where_text)}`, pick: `inc:${x.id}` } })),
      ...news.map((f, i) => ({ ...f, properties: { color: NEWS_COLOR, radius: 8, stroke: "#111014",
        title: `<b>${esc(f.properties.articles[0]?.title ?? "News")}</b><br/>near ${esc(f.properties.near_name)}`, pick: `news:${i}` } })),
    ];
    return { lines: fc(g.lines), points: fc(pts) };
  }, [incidents, projects, openId, news]);

  const openIncident = (id: number) => {
    const inc = all.find((x) => x.id === id);
    if (inc) setFit({ bbox: around(inc.lon, inc.lat), key: `i${id}${Date.now()}`, maxZoom: 10 });
    publicApi.get<IncidentDetail>(`/api/incidents/${id}`).then((d) => setOpen({ kind: "incident", detail: d })).catch(() => {});
  };
  const openNews = (i: number) => {
    const [lon, lat] = news[i].geometry.coordinates;
    setOpen({ kind: "news", idx: i });
    setFit({ bbox: around(lon, lat), key: `n${i}${Date.now()}`, maxZoom: 10 });
  };
  const onPick = (p: string) => {
    if (p.startsWith("inc:")) openIncident(Number(p.slice(4)));
    else if (p.startsWith("news:")) openNews(Number(p.slice(5)));
  };
  const toggle = (k: string) => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  const legend = kinds.length > 0 && (
    <div className="absolute right-3 top-3 flex flex-col gap-0.5 rounded-2xl border-2 border-pen bg-white/95 px-1.5 py-1.5 text-[11px] font-semibold">
      {kinds.map(({ k, n }) => (
        <button key={k} onClick={() => toggle(k)} aria-pressed={!hidden.has(k)}
          className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 text-left ${hidden.has(k) ? "text-faint line-through" : "hover:bg-soft"}`}>
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: hidden.has(k) ? "#d5dae5" : kindOf(k).color }} /><span className="flex-1">{kindOf(k).label}</span><span className="text-faint">{n}</span>
        </button>
      ))}
      {news.length > 0 && <span className="flex items-center gap-1.5 px-2 py-0.5"><span className="h-2.5 w-2.5 rounded-full border-2 border-pen" style={{ background: NEWS_COLOR }} />News</span>}
    </div>
  );

  const list = (
    <>
      <PanelHeader title="News & damage" sub={replay ? "Sept 27, 2024, the morning after Helene" : "Reports from the last few days"} />
      <ScenarioSwitch value={scenario} onChange={setScenario} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1 overflow-y-auto pr-2">
        {!frame && !err && <p className="text-sm text-muted"><span className="dots">Reading the news</span></p>}
        {err && <p className="text-sm text-warn">{err}</p>}
        {frame && (
          <div className="mb-1 grid grid-cols-3 gap-1.5 text-center">
            {[["Reports", all.length], ["Verified", all.filter((x) => x.verified).length], ["News", news.length]].map(([l, n]) => (
              <div key={l} className="rounded-xl bg-soft py-1.5"><div className="font-logo text-lg font-semibold leading-none">{n}</div><div className="text-[11px] font-semibold text-muted">{l}</div></div>
            ))}
          </div>
        )}
        {!replay && stories && stories.length > 0 && (
          <>
            <SectionTitle><AlertTriangle size={13} /> For us · {forUs.length}</SectionTitle>
            <div className="mb-1 flex flex-wrap gap-1 px-2">
              {impacts.map(([k, n]) => (
                <button key={k} onClick={() => setImpact(impact === k ? null : k)} aria-pressed={impact === k}
                  className={`flex items-center gap-1 rounded-full border-2 px-2 py-0.5 text-[11px] font-semibold ${impact === k ? "border-pen bg-grape-soft" : "border-line bg-white hover:border-ink"}`}>
                  <span className="h-2 w-2 rounded-full" style={{ background: impactOf(k).color }} />{impactOf(k).label}<span className="text-faint">{n}</span>
                </button>
              ))}
            </div>
            {forUs.slice(0, 40).map((s) => (
              <button key={s.id} onClick={() => setOpen({ kind: "story", item: s })} className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
                <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: impactOf(s.impact).color, opacity: s.affects_work ? 1 : 0.45 }} />
                <span className="min-w-0">
                  <span className="line-clamp-2 block text-sm font-semibold leading-snug">{s.title}</span>
                  <span className="block text-xs text-muted">
                    {impactOf(s.impact).label} · {s.about.join(", ")}{s.opportunity_ids.length ? ` · overlap #${s.opportunity_ids[0]}` : s.job_ids.length ? " · one of our projects" : ""}
                    {s.published ? ` · ${ago(s.published)}` : ""}
                  </span>
                </span>
              </button>
            ))}
            {!forUs.length && <p className="px-2 py-2 text-xs text-muted">No stories with that impact.</p>}
          </>
        )}
        {!replay && stories && !stories.length && <p className="px-2 py-1 text-xs text-muted">No recent stories about us or our neighbors yet.</p>}
        {news.length > 0 && <SectionTitle><Newspaper size={13} /> In the news</SectionTitle>}
        {news.slice(0, 12).map((f, i) => {
          const a = f.properties.articles[0];
          return (
            <button key={i} onClick={() => openNews(i)} className="rounded-2xl px-2 py-2 text-left hover:bg-soft">
              <span className="block text-xs text-muted">{a?.source} · near {f.properties.near_name}</span>
              <span className="line-clamp-2 block text-sm font-semibold leading-snug">{a?.title}</span>
            </button>
          );
        })}
        {incidents.length > 0 && <SectionTitle>Damage reports · {incidents.length}</SectionTitle>}
        {incidents.slice(0, 80).map((x) => (
          <button key={x.id} onClick={() => openIncident(x.id)} className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
            <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: kindOf(x.kind).color, opacity: x.verified ? 1 : 0.5 }} />
            <span className="min-w-0">
              <span className="block text-sm font-semibold leading-snug">{kindOf(x.kind).label}{!x.verified && <span className="ml-1.5 text-xs font-normal text-muted">unconfirmed</span>}</span>
              <span className="block text-xs text-muted">{x.where_text} · {when(x.ts, replay, ago)}</span>
            </span>
          </button>
        ))}
        {incidents.length > 80 && <p className="px-2 text-xs text-muted">and {incidents.length - 80} more on the map</p>}
        {frame && !all.length && !news.length && (
          <div className="rounded-2xl bg-save-soft/70 px-3 py-2.5 text-sm">
            <div className="font-semibold text-save">No damage reported</div>
            <p className="mt-0.5 text-xs text-muted">Nothing from storm reports or the news near your area right now.</p>
            {!replay && <button onClick={() => setScenario("helene")} className="mt-1.5 text-xs font-semibold text-grape underline">See the day after Helene</button>}
          </div>
        )}
      </div>
    </>
  );

  let detail: React.ReactNode = null;
  if (open?.kind === "story") {
    const s = open.item;
    const ev = s.evidence ?? {};
    detail = (
      <>
        <PanelHeader title={impactOf(s.impact).label} sub={`${s.source ?? "News"}${s.published ? ` · ${ago(s.published)}` : ""}`} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
          <div className="text-sm font-semibold leading-snug">{s.title}</div>
          <div className="flex flex-wrap gap-1.5 text-xs font-semibold">
            <span className={`rounded-full px-2 py-0.5 ${s.affects_work ? "bg-warn-soft text-warn" : "bg-soft text-muted"}`}>{s.affects_work ? "Could affect the work" : "Background"}</span>
            <span className={`rounded-full px-2 py-0.5 ${s.verified ? "bg-save-soft text-save" : "bg-soft text-muted"}`}>{s.verified ? "Matches an official report" : "Unverified"}</span>
            <span className="rounded-full bg-soft px-2 py-0.5">{Math.round(s.confidence * 100)}% link confidence</span>
          </div>
          {s.summary && <p className="rounded-2xl rounded-tl-sm bg-soft px-3 py-2 text-sm">{s.summary}</p>}
          <div className="rounded-xl border-2 border-line px-2.5 py-2 text-xs">
            <div className="mb-0.5 font-semibold text-muted">Why it is linked</div>
            <div>About {s.about.join(" and ")}{ev.org?.length ? ` (named: ${ev.org.join(", ")})` : ""}.</div>
            {ev.station?.length ? <div>Stations named: {ev.station.join(", ")}.</div> : null}
            {ev.county?.length ? <div>Counties named: {ev.county.join(", ")}.</div> : null}
            {ev.keyword ? <div>Impact word: "{ev.keyword}".</div> : null}
            {ev.verified_by ? <div>Official report nearby: {Object.values(ev.verified_by).join(", ")}.</div> : null}
          </div>
          {s.opportunity_ids.length > 0 && onOpenOverlap && (
            <div className="flex flex-wrap gap-1.5">
              {s.opportunity_ids.slice(0, 4).map((id) => (
                <button key={id} onClick={() => onOpenOverlap(id)} className="flex items-center gap-1 rounded-full border-2 border-pen bg-white px-2.5 py-1 text-xs font-semibold hover:bg-grape-soft"><MapPin size={12} /> Open overlap #{id}</button>
              ))}
            </div>
          )}
          <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Read the story <ExternalLink size={11} /></a>
        </div>
      </>
    );
  } else if (open?.kind === "incident") {
    const d = open.detail;
    detail = (
      <>
        <PanelHeader title={kindOf(d.kind).label} sub={`${d.where_text} · ${when(d.ts, replay, ago)}`} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
          <div className="flex flex-wrap gap-1.5 text-xs font-semibold">
            <span className={`rounded-full px-2 py-0.5 ${d.verified ? "bg-save-soft text-save" : "bg-crew-soft text-[#8a5a00]"}`}>{d.verified ? "Verified" : "Unconfirmed"}</span>
            <span className="rounded-full bg-soft px-2 py-0.5">{Math.round(d.confidence * 100)}% confidence</span>
            {d.customers_affected != null && <span className="rounded-full bg-soft px-2 py-0.5">{d.customers_affected.toLocaleString()} customers</span>}
          </div>
          <Near projects={projects} lon={d.lon} lat={d.lat} />
          <h3 className="mt-1 text-sm font-semibold text-muted">Source{d.sources.length === 1 ? "" : "s"}</h3>
          {d.sources.map((s, i) => (
            <div key={i} className="rounded-xl border-2 border-line px-2.5 py-2 text-sm">
              <div className="text-xs font-semibold text-muted">{s.name}{s.type === "official" ? " · official" : ""}</div>
              {s.title && <div className="font-semibold leading-snug">{s.title}</div>}
              {s.quote_evidence && <p className="mt-0.5 line-clamp-4 text-xs italic text-muted">"{s.quote_evidence}"</p>}
              {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Open <ExternalLink size={11} /></a>}
            </div>
          ))}
        </div>
      </>
    );
  } else if (open?.kind === "news" && news[open.idx]) {
    const p = news[open.idx].properties;
    const [lon, lat] = news[open.idx].geometry.coordinates;
    detail = (
      <>
        <PanelHeader title="In the news" sub={`Near ${p.near_name}${p.near_mi != null ? ` · ${p.near_mi} mi` : ""}`} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
          <div className="flex flex-wrap gap-1.5 text-xs font-semibold">
            <span className={`rounded-full px-2 py-0.5 ${p.verified ? "bg-save-soft text-save" : "bg-crew-soft text-[#8a5a00]"}`}>{p.verified ? "Confirmed by 2+ sources" : "Single source"}</span>
            <span className="rounded-full bg-soft px-2 py-0.5 capitalize">{p.topic}</span>
          </div>
          <Near projects={projects} lon={lon} lat={lat} />
          {p.articles.map((a, i) => (
            <div key={i} className="rounded-xl border-2 border-line px-2.5 py-2 text-sm">
              <div className="text-xs font-semibold text-muted">{a.source}{a.published ? ` · ${when(a.published, replay, ago)}` : ""}{a.copies > 1 ? ` · ${a.copies} copies` : ""}</div>
              <div className="font-semibold leading-snug">{a.title}</div>
              {a.quote && <p className="mt-0.5 line-clamp-4 text-xs italic text-muted">"{a.quote.trim()}"</p>}
              <a href={a.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Read <ExternalLink size={11} /></a>
            </div>
          ))}
        </div>
      </>
    );
  }

  return <Split map={<MapPane scene={scene} fit={fit} onPick={onPick}>{legend}</MapPane>} side={side ?? detail ?? list} />;
}
