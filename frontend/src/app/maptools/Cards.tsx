import { BookOpen, CalendarRange, Check, CloudSun, Copy, Download as DownloadIcon, ExternalLink, Link2, MapPinned, Route as RouteIcon, Sigma, Trash2 } from "lucide-react";
import { useState } from "react";
import { API_BASE } from "../../apiBase";
import { api, supabase, usd } from "../data";
import { download as saveBlob, fmt } from "../generate/types";
import { kb, type Download, type Explain, type Forecast, type MapCard, type Projects, type Result, type Route, type Share, type Timeline } from "./types";

const money = (v: unknown, unit?: string) => (unit === "$" || unit === "USD" ? fmt(v, "USD") : `${fmt(v)}${unit ? ` ${unit}` : ""}`);
const result = (r: Result) => r.verdict ? `${r.verdict}${r.value != null ? ` (${fmt(r.value)})` : ""}` : r.low != null && r.high != null ? `${money(r.low, r.unit)} to ${money(r.high, r.unit)}` : money(r.value, r.unit);

export type CardProps = { onPickProject?: (id: string, mine?: boolean) => void; onOpenTimeline?: (t: Timeline) => void; onShowRoute?: (r: Route) => void; onOpen?: (overlapId: number) => void };

const Box = ({ icon, title, sub, children, right }: { icon: React.ReactNode; title: string; sub?: string; children?: React.ReactNode; right?: React.ReactNode }) => (
  <div className="pop-in rounded-2xl border-2 border-pen bg-white p-2">
    <div className="flex items-start gap-2 px-1">
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-grape-soft text-grape">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold leading-snug">{title}</div>
        {sub && <div className="text-[11px] text-muted">{sub}</div>}
      </div>
      {right}
    </div>
    {children}
  </div>
);

const Pill = ({ onClick, children, primary }: { onClick: () => void; children: React.ReactNode; primary?: boolean }) => (
  <button onClick={onClick} className={`flex items-center gap-1 rounded-full border-2 px-2.5 py-0.5 text-xs font-semibold ${primary ? "border-pen bg-white hover:bg-grape-soft" : "border-line hover:border-pen"}`}>{children}</button>
);

const authedBlob = async (path: string) => {
  const token = (await supabase.auth.getSession()).data.session?.access_token;
  const res = await fetch(`${API_BASE}${path}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(res.statusText);
  return res.blob();
};

// the projects a filter picked: a tappable list, each one flies the map to it
export function ProjectsCard({ projects, onPickProject }: { projects: Projects } & CardProps) {
  const [all, setAll] = useState(false);
  const rows = all ? projects.rows : projects.rows.slice(0, 8);
  return (
    <Box icon={<MapPinned size={16} />} title={projects.title} sub={`${projects.rows.length} project${projects.rows.length === 1 ? "" : "s"} · highlighted on the map`}>
      <div className="mt-1 flex flex-col">
        {rows.map((r) => (
          <button key={r.id} onClick={() => onPickProject?.(r.id, true)} className="flex items-center gap-2 rounded-xl px-2 py-1 text-left hover:bg-soft">
            <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
            <span className="shrink-0 text-[11px] text-muted">{r.kv ? `${r.kv} kV · ` : ""}{r.start.slice(0, 4)}–{r.end.slice(0, 4)}{r.cost_usd ? ` · ${usd(r.cost_usd)}` : ""}</span>
          </button>
        ))}
        {projects.rows.length > 8 && <button onClick={() => setAll(!all)} className="px-2 py-1 text-left text-xs font-semibold text-grape">{all ? "Fewer" : `All ${projects.rows.length}`}</button>}
      </div>
    </Box>
  );
}

// build windows on a calendar: a summary here, the full month grid replaces the map
export function TimelineCard({ timeline, onOpenTimeline, onPickProject }: { timeline: Timeline } & CardProps) {
  const mine = timeline.rows.filter((r) => r.mine).length;
  return (
    <Box icon={<CalendarRange size={16} />} title={timeline.title} sub={`${mine} of ours${timeline.rows.length > mine ? `, ${timeline.rows.length - mine} of theirs` : ""}`}
      right={<Pill primary onClick={() => onOpenTimeline?.(timeline)}><CalendarRange size={12} /> Show grid</Pill>}>
      <div className="mt-1 flex flex-col">
        {timeline.rows.slice(0, 6).map((r) => (
          <button key={`${r.org}-${r.id}`} onClick={() => onPickProject?.(r.id, r.mine)} className="flex items-center gap-2 rounded-xl px-2 py-1 text-left hover:bg-soft">
            <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
            <span className="shrink-0 text-[11px] text-muted">{r.org_short} · {r.start.slice(0, 7)} to {r.end.slice(0, 7)}</span>
          </button>
        ))}
        {timeline.rows.length > 6 && <span className="px-2 py-1 text-xs text-faint">and {timeline.rows.length - 6} more on the grid</span>}
      </div>
    </Box>
  );
}

const DAY_COLS: { key: keyof Forecast["days"][number]; label: string; unit: string }[] = [
  { key: "gust_mph", label: "Gust", unit: " mph" }, { key: "thunder_pct", label: "Thunder", unit: "%" }, { key: "rain_in", label: "Rain", unit: " in" }, { key: "heat_index_f", label: "Heat idx", unit: "°F" },
];

// seven days at a site against the stop rules: quiet days are green, days with a note say why
export function ForecastCard({ forecast }: { forecast: Forecast }) {
  const busy = forecast.days.filter((d) => d.notes.length);
  return (
    <Box icon={<CloudSun size={16} />} title={`Forecast: ${forecast.site}`} sub={`${forecast.near ? `near ${forecast.near} · ` : ""}${busy.length ? `${busy.length} day${busy.length === 1 ? "" : "s"} with a work note` : "a quiet week"} · NWS`}>
      <div className="mt-1 overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead><tr className="text-left text-faint"><th className="px-1 py-0.5 font-semibold">Day</th>{DAY_COLS.map((c) => <th key={c.key} className="px-1 py-0.5 font-semibold">{c.label}</th>)}<th className="px-1 py-0.5 font-semibold">Hi/Lo</th></tr></thead>
          <tbody>
            {forecast.days.map((d) => (
              <tr key={d.date} className={d.notes.length ? "bg-warn-soft" : ""} title={d.notes.join("; ")}>
                <td className="px-1 py-0.5 font-semibold">{d.dow} {d.date.slice(5)}</td>
                {DAY_COLS.map((c) => <td key={c.key} className="px-1 py-0.5 tabular-nums">{d[c.key] == null ? "–" : `${fmt(d[c.key])}${c.unit}`}</td>)}
                <td className="px-1 py-0.5 tabular-nums">{d.high_f ?? "–"}/{d.low_f ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {busy.length > 0 && <ul className="mt-1 flex flex-col gap-0.5 px-1 text-[11px] text-muted">{busy.map((d) => <li key={d.date}><b>{d.dow}</b>: {d.notes.join(", ")}</li>)}</ul>}
      <div className="px-1 pt-1 text-[10px] text-faint">fetched {forecast.fetched_at.slice(0, 16).replace("T", " ")} UTC · {forecast.source}</div>
    </Box>
  );
}

// a drive between two places, drawn on the map
export function RouteCard({ route, onShowRoute }: { route: Route } & CardProps) {
  return (
    <Box icon={<RouteIcon size={16} />} title={`${route.from} → ${route.to}`}
      sub={route.drive_min != null ? `${route.road_mi} mi by road · about ${Math.round(route.drive_min)} min` : `${route.straight_mi} mi straight line`}
      right={<Pill primary onClick={() => onShowRoute?.(route)}><MapPinned size={12} /> On map</Pill>}>
      <div className="px-1 pt-1 text-[11px] text-muted">{route.note ?? `straight line ${route.straight_mi} mi · ${route.source}`}</div>
    </Box>
  );
}

// a file crewly built, fetched with the login and saved from the browser
export function DownloadCard({ download }: { download: Download }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "err">("idle");
  const save = async () => {
    setState("busy");
    try { saveBlob(download.filename, await authedBlob(`/api/app/export/${download.id}`)); setState("done"); } catch { setState("err"); }
  };
  const filters = Object.entries(download.filters ?? {}).map(([k, v]) => `${k} ${Array.isArray(v) ? v.join("–") : String(v)}`).join(" · ");
  return (
    <Box icon={<DownloadIcon size={16} />} title={download.filename} sub={`${download.kind} as ${download.format.toUpperCase()} · ${kb(download.size)}${filters ? ` · ${filters}` : ""}`}
      right={<Pill primary onClick={save}>{state === "busy" ? "Saving" : state === "done" ? <><Check size={12} /> Saved</> : state === "err" ? "Retry" : <><DownloadIcon size={12} /> Save</>}</Pill>} />
  );
}

// an expiring public link; copy it, open it, or revoke it here
export function ShareCard({ share }: { share: Share }) {
  const [copied, setCopied] = useState(false);
  const [revoked, setRevoked] = useState(false);
  const url = `${API_BASE || window.location.origin}${share.path}`;
  const copy = async () => { try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard blocked: the link is still shown */ } };
  const revoke = async () => { try { await api.send(`/api/app/share/${share.id}`, "DELETE"); setRevoked(true); } catch { /* keep the card */ } };
  return (
    <Box icon={<Link2 size={16} />} title={share.title} sub={revoked ? "link revoked" : `${share.kind} · anyone with the link · expires ${share.expires_at.slice(0, 10)}`}>
      {!revoked && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 px-1">
          <input readOnly value={url} onFocus={(e) => e.currentTarget.select()} aria-label="Share link" className="min-w-0 flex-1 rounded-full border-2 border-line bg-soft px-2 py-0.5 text-[11px]" />
          <Pill primary onClick={copy}>{copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}</Pill>
          <Pill onClick={() => window.open(url, "_blank")}><ExternalLink size={12} /> Open</Pill>
          <Pill onClick={revoke}><Trash2 size={12} /> Revoke</Pill>
        </div>
      )}
    </Box>
  );
}

// how a number was made: the formula, the inputs with where they came from, the steps, and the sources
export function ExplainCard({ explain, onOpen }: { explain: Explain } & CardProps) {
  const [more, setMore] = useState(false);
  const method = !explain.inputs.length && !explain.steps.length;
  return (
    <Box icon={method ? <BookOpen size={16} /> : <Sigma size={16} />} title={explain.title} sub={explain.opportunity_id ? `overlap #${explain.opportunity_id}` : undefined}
      right={explain.opportunity_id ? <Pill onClick={() => onOpen?.(explain.opportunity_id!)}>Open</Pill> : undefined}>
      <p className="mt-1 whitespace-pre-line px-1 text-[12px] leading-snug">{explain.formula}</p>
      {explain.inputs.length > 0 && (
        <table className="mt-1 w-full text-[11px]"><tbody>
          {explain.inputs.map((i, k) => <tr key={k} className="border-t border-line"><td className="px-1 py-0.5 text-muted">{i.label}</td><td className="px-1 py-0.5 text-right font-semibold tabular-nums">{fmt(i.value)}</td><td className="px-1 py-0.5 text-right text-[10px] text-faint">{i.source ?? i.unit ?? ""}</td></tr>)}
        </tbody></table>
      )}
      {explain.steps.length > 0 && <ol className="mt-1 list-decimal flex-col gap-0.5 px-1 pl-5 text-[11px] text-muted">{explain.steps.map((s, k) => <li key={k}>{s}</li>)}</ol>}
      {explain.result && <div className="mt-1 px-1 text-sm font-semibold">{result(explain.result)}</div>}
      {(explain.assumptions?.length ?? 0) > 0 && (
        <div className="mt-1 px-1">
          <button onClick={() => setMore(!more)} className="text-[11px] font-semibold text-grape">{more ? "Hide" : "Show"} assumptions ({explain.assumptions!.length})</button>
          {more && <ul className="mt-0.5 flex flex-col gap-0.5 text-[11px] text-muted">{explain.assumptions!.map((a) => <li key={a.key}>{a.label}: <b>{result(a)}</b>{a.verified === false ? " · proxy" : ""}{a.source ? ` · ${a.source}${a.page ? `, p. ${a.page}` : ""}` : ""}</li>)}</ul>}
        </div>
      )}
      {explain.sources.length > 0 && <div className="mt-1 flex flex-wrap gap-1 px-1">{explain.sources.map((s) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="rounded-full bg-soft px-2 py-0.5 text-[10px] text-muted hover:text-ink">{s.title}</a>)}</div>}
    </Box>
  );
}

// one dispatcher so the chat renders any of these with a single line
export function MapCards({ cards, ...p }: { cards: MapCard[] } & CardProps) {
  return <>{cards.map((c, i) => {
    switch (c.type) {
      case "projects": return <ProjectsCard key={i} projects={c.projects} {...p} />;
      case "timeline": return <TimelineCard key={i} timeline={c.timeline} {...p} />;
      case "forecast": return <ForecastCard key={i} forecast={c.forecast} />;
      case "route": return <RouteCard key={i} route={c.route} {...p} />;
      case "download": return <DownloadCard key={i} download={c.download} />;
      case "share": return <ShareCard key={i} share={c.share} />;
      case "explain": return <ExplainCard key={i} explain={c.explain} {...p} />;
      default: return null;
    }
  })}</>;
}
