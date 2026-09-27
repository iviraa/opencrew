import { AlertTriangle, ExternalLink, HardHat, MapPin, Newspaper } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { say, type Mood } from "../mascot";
import type { NewsPin } from "../../api";
import { ago, api, publicApi, type Jobs } from "../data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { Chip, ConfidenceChip, Disc, Dot, ListRow, Meta, PanelHeader, count } from "../panels";
import { SectionTitle, Split, around, fc, nearestProject, splitGeoms } from "./shared";

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
    <div className="card-still flex items-center gap-2.5 px-3 py-2 text-sm">
      <HardHat size={15} className="shrink-0 text-muted" />
      <span className="min-w-0"><span className="block text-[11px] font-semibold uppercase tracking-wide text-faint">Nearest of your projects</span><b>{n.name}</b> <span className="text-muted">· {n.mi < 1 ? n.mi.toFixed(1) : Math.round(n.mi)} mi</span></span>
    </div>
  );
}

// one short line for the beaver about damage reports
function newsLine(f: LiveFrame): [string, Mood] {
  const n = f.incidents.features.length, v = f.incidents.features.filter((x) => x.properties.verified).length, a = f.news.features.length;
  if (!n && !a) return ["No damage reports right now.", "happy"];
  if (!n) return [`${a} news story${a === 1 ? "" : "s"} near our area, no damage reports.`, "nod"];
  return [`${n} damage report${n === 1 ? "" : "s"} found, ${v} verified.`, "surprised"];
}

export default function NewsTab({ projects, side, onOpenOverlap }: { projects: Jobs | null; side: React.ReactNode | null; onOpenOverlap?: (id: number) => void }) {
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

  useEffect(() => {
    setFrame(null); setOpen(null); setErr(null); setHidden(new Set());
    say("Reading the latest news...", "thinking");
    publicApi.get<LiveFrame>("/api/live/frame?scenario=none").then((f) => {
      setFrame(f);
      say(...newsLine(f));
      const b = bboxOf([f.incidents, f.news]);
      if (b) setFit({ bbox: b, key: `news${Date.now()}`, maxZoom: 9 });
    }).catch((e) => { setErr(String(e)); say("I couldn't load the news.", "sad"); });
  }, []);

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
      <PanelHeader title="News & damage" sub="Reports from the last few days" />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto px-0.5 pb-1 pr-2">
        {!frame && !err && <p className="text-sm text-muted"><span className="dots">Reading the news</span></p>}
        {err && <p className="text-sm text-warn">{err}</p>}
        {frame && (
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["Reports", all.length], ["Verified", all.filter((x) => x.verified).length], ["Nearby news", news.length]].map(([l, n]) => (
              <div key={l} className="card-still py-2"><div className="font-logo text-lg font-semibold leading-none tabular-nums">{count(Number(n))}</div><div className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-faint">{l}</div></div>
            ))}
          </div>
        )}
        {stories && stories.length > 0 && (
          <>
            <SectionTitle><AlertTriangle size={13} /> For us · {forUs.length}</SectionTitle>
            <div className="flex flex-wrap gap-1 px-1">
              {impacts.map(([k, n]) => (
                <button key={k} onClick={() => setImpact(impact === k ? null : k)} aria-pressed={impact === k}
                  className={`flex items-center gap-1 rounded-full border-2 px-2 py-0.5 text-[11px] font-semibold ${impact === k ? "border-pen bg-grape-soft" : "border-line bg-white hover:border-ink"}`}>
                  <span className="h-2 w-2 rounded-full" style={{ background: impactOf(k).color }} />{impactOf(k).label}<span className="tabular-nums text-faint">{n}</span>
                </button>
              ))}
            </div>
            {forUs.slice(0, 40).map((s) => (
              <ListRow key={s.id} onClick={() => setOpen({ kind: "story", item: s })} lead={<Dot color={impactOf(s.impact).color} dim={!s.affects_work} />} title={s.title}
                right={s.affects_work ? <Chip tone="warn">Affects work</Chip> : undefined}
                sub={[impactOf(s.impact).label, s.about.join(", "), s.opportunity_ids.length ? `overlap #${s.opportunity_ids[0]}` : s.job_ids.length ? "one of our projects" : "", s.published ? ago(s.published) : ""].filter(Boolean).join(" · ")} />
            ))}
            {!forUs.length && <p className="px-2 py-2 text-xs text-muted">No stories with that impact.</p>}
          </>
        )}
        {stories && !stories.length && <p className="px-2 py-1 text-xs text-muted">No recent stories about us or our neighbors yet.</p>}
        {news.length > 0 && <SectionTitle><Newspaper size={13} /> In the news</SectionTitle>}
        {news.slice(0, 12).map((f, i) => {
          const a = f.properties.articles[0];
          return <ListRow key={i} onClick={() => openNews(i)} lead={<Dot color={NEWS_COLOR} />} title={a?.title} sub={`${a?.source ?? "News"} · near ${f.properties.near_name}`} />;
        })}
        {incidents.length > 0 && <SectionTitle>Damage reports · {incidents.length}</SectionTitle>}
        {incidents.slice(0, 80).map((x) => (
          <ListRow key={x.id} onClick={() => openIncident(x.id)} active={openId === x.id} lead={<Dot color={kindOf(x.kind).color} dim={!x.verified} />}
            title={kindOf(x.kind).label} sub={`${x.where_text} · ${ago(x.ts)}`} right={<Chip tone={x.verified ? "good" : "neutral"}>{x.verified ? "Verified" : "Unconfirmed"}</Chip>} />
        ))}
        {incidents.length > 80 && <p className="px-2 text-xs text-muted">and {incidents.length - 80} more on the map</p>}
        {frame && !all.length && !news.length && (
          <div className="rounded-2xl border-2 border-save/30 bg-save-soft/60 px-3 py-2.5 text-sm">
            <div className="font-semibold text-save">No damage reported</div>
            <p className="mt-0.5 text-xs text-muted">Nothing from storm reports or the news near your area right now.</p>
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
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2.5 overflow-y-auto px-0.5 pb-1 pr-2">
          <div className="card-still px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Chip tone="neutral" icon={<span className="h-2 w-2 rounded-full" style={{ background: impactOf(s.impact).color }} />}>{impactOf(s.impact).label}</Chip>
              <span className="text-xs text-faint">{s.published ? ago(s.published) : "undated"}</span>
            </div>
            <div className="mt-1.5 text-sm font-semibold leading-snug">{s.title}</div>
            {s.summary && <p className="mt-1.5 text-sm leading-snug text-muted">{s.summary}</p>}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Chip tone={s.affects_work ? "warn" : "neutral"}>{s.affects_work ? "Could affect the work" : "Background"}</Chip>
              <Chip tone={s.verified ? "good" : "neutral"}>{s.verified ? "Matches an official report" : "Unverified"}</Chip>
              <ConfidenceChip value={s.confidence} label="Link confidence" />
            </div>
          </div>
          <div className="card-still px-3 py-2.5">
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Why it is linked</div>
            <Meta rows={[
              ["About", `${s.about.join(" and ")}${ev.org?.length ? ` (named ${ev.org.join(", ")})` : ""}`],
              ["Stations", ev.station?.length ? ev.station.join(", ") : ""],
              ["Counties", ev.county?.length ? ev.county.join(", ") : ""],
              ["Impact word", ev.keyword ? `"${ev.keyword}"` : ""],
              ["Official report", ev.verified_by ? Object.values(ev.verified_by).join(", ") : ""],
            ]} />
          </div>
          {s.opportunity_ids.length > 0 && onOpenOverlap && (
            <div className="flex flex-wrap gap-1.5">
              {s.opportunity_ids.slice(0, 4).map((id) => (
                <button key={id} onClick={() => onOpenOverlap(id)} className="inline-flex items-center gap-1 rounded-full border-2 border-pen bg-white px-2.5 py-1 text-xs font-semibold hover:bg-grape-soft"><MapPin size={12} /> Open overlap #{id}</button>
              ))}
            </div>
          )}
          <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 self-start text-xs font-semibold text-grape hover:underline">Read the story <ExternalLink size={11} /></a>
        </div>
      </>
    );
  } else if (open?.kind === "incident") {
    const d = open.detail;
    detail = (
      <>
        <PanelHeader title={kindOf(d.kind).label} sub={`${d.where_text} · ${ago(d.ts)}`} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2.5 overflow-y-auto px-0.5 pb-1 pr-2">
          <div className="card-still px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Disc color={kindOf(d.kind).color}><AlertTriangle size={14} /></Disc>
              <span className="min-w-0 flex-1 text-sm font-semibold leading-snug">{kindOf(d.kind).label}</span>
              <Chip tone={d.verified ? "good" : "warn"}>{d.verified ? "Verified" : "Unconfirmed"}</Chip>
            </div>
            <div className="mt-2.5">
              <Meta rows={[
                ["Where", d.where_text],
                ["Reported", new Date(d.ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })],
                ["Sources", `${d.sources.length} ${d.sources.length === 1 ? "source" : "sources"}`],
                ["Customers", d.customers_affected != null ? `${count(d.customers_affected)} affected` : ""],
              ]} />
            </div>
            <div className="mt-2.5"><ConfidenceChip value={d.confidence} /></div>
          </div>
          <Near projects={projects} lon={d.lon} lat={d.lat} />
          <SectionTitle>Source{d.sources.length === 1 ? "" : "s"}</SectionTitle>
          {d.sources.map((s, i) => (
            <div key={i} className="card-still px-3 py-2.5 text-sm">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted"><span className="min-w-0 flex-1 truncate">{s.name}</span>{s.type === "official" && <Chip tone="info">Official</Chip>}</div>
              {s.title && <div className="mt-0.5 font-semibold leading-snug">{s.title}</div>}
              {s.quote_evidence && <p className="mt-1 line-clamp-4 text-xs italic leading-snug text-muted">"{s.quote_evidence}"</p>}
              {s.url && <a href={s.url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Open source <ExternalLink size={11} /></a>}
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
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2.5 overflow-y-auto px-0.5 pb-1 pr-2">
          <div className="flex flex-wrap gap-1.5">
            <Chip tone={p.verified ? "good" : "neutral"}>{p.verified ? "Confirmed by two or more sources" : "Single source"}</Chip>
            <Chip tone="info"><span className="capitalize">{p.topic}</span></Chip>
          </div>
          <Near projects={projects} lon={lon} lat={lat} />
          {p.articles.map((a, i) => (
            <div key={i} className="card-still px-3 py-2.5 text-sm">
              <div className="flex items-center gap-2 text-xs font-semibold text-muted">
                <span className="min-w-0 flex-1 truncate">{a.source}{a.published ? ` · ${ago(a.published)}` : ""}</span>
                {a.copies > 1 && <Chip>{a.copies} copies</Chip>}
              </div>
              <div className="mt-0.5 font-semibold leading-snug">{a.title}</div>
              {a.quote && <p className="mt-1 line-clamp-4 text-xs italic leading-snug text-muted">"{a.quote.trim()}"</p>}
              <a href={a.url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-xs font-semibold text-grape hover:underline">Read the article <ExternalLink size={11} /></a>
            </div>
          ))}
        </div>
      </>
    );
  }

  return <Split map={<MapPane scene={scene} fit={fit} onPick={onPick}>{legend}</MapPane>} side={side ?? detail ?? list} />;
}
