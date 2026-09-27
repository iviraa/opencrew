import { BookOpen, CalendarRange, Check, CloudSun, Copy, Download as DownloadIcon, ExternalLink, Link2, MapPinned, Route as RouteIcon, Sigma, Trash2 } from "lucide-react";
import { useState } from "react";
import { API_BASE } from "../../apiBase";
import { api, supabase, usd } from "../data";
import { download as saveBlob, fmt } from "../generate/types";
import { Card, Chip, Drawer, Lead, Note, Pill, RefLink, Row, StatRow, plural } from "../ui";
import { kb, type Download, type Explain, type Forecast, type MapCard, type Projects, type Result, type Route, type Share, type Timeline } from "./types";

const money = (v: unknown, unit?: string) => (unit === "$" || unit === "USD" ? fmt(v, "USD") : `${fmt(v)}${unit ? ` ${unit}` : ""}`);
const result = (r: Result) => r.verdict ? `${r.verdict}${r.value != null ? ` (${fmt(r.value)})` : ""}` : r.low != null && r.high != null ? `${money(r.low, r.unit)} to ${money(r.high, r.unit)}` : money(r.value, r.unit);

export type CardProps = { onPickProject?: (id: string, mine?: boolean) => void; onOpenTimeline?: (t: Timeline) => void; onShowRoute?: (r: Route) => void; onOpen?: (overlapId: number) => void };

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
    <Card icon={<MapPinned size={15} />} title={projects.title} sub={`${plural(projects.rows.length, "project")} highlighted on the map · tap one to fly there`}>
      <div className="flex flex-col">
        {rows.map((r) => (
          <button key={r.id} onClick={() => onPickProject?.(r.id, true)} className="flex items-center gap-2 rounded-xl px-2 py-1 text-left hover:bg-soft">
            <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
            <span className="shrink-0 text-[11px] tabular-nums text-muted">{r.kv ? `${r.kv} kV · ` : ""}{r.start.slice(0, 4)}–{r.end.slice(0, 4)}{r.cost_usd ? ` · ${usd(r.cost_usd)}` : ""}</span>
          </button>
        ))}
        {projects.rows.length > 8 && <Pill onClick={() => setAll(!all)} className="self-start">{all ? "Show fewer" : `Show all ${projects.rows.length}`}</Pill>}
      </div>
    </Card>
  );
}

// build windows on a calendar: a summary here, the full month grid replaces the map
export function TimelineCard({ timeline, onOpenTimeline, onPickProject }: { timeline: Timeline } & CardProps) {
  const mine = timeline.rows.filter((r) => r.mine).length;
  return (
    <Card icon={<CalendarRange size={15} />} title={timeline.title} sub={`${mine} of ours${timeline.rows.length > mine ? `, ${timeline.rows.length - mine} of theirs` : ""} · ${timeline.years[0]} to ${timeline.years[1]}`}
      right={<Pill primary onClick={() => onOpenTimeline?.(timeline)} icon={<CalendarRange size={12} />}>Grid</Pill>}>
      <div className="flex flex-col">
        {timeline.rows.slice(0, 6).map((r) => (
          <button key={`${r.org}-${r.id}`} onClick={() => onPickProject?.(r.id, r.mine)} className="flex items-center gap-2 rounded-xl px-2 py-1 text-left hover:bg-soft">
            <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
            <span className="shrink-0 text-[11px] text-muted">{r.org_short} · {r.start.slice(0, 7)} to {r.end.slice(0, 7)}</span>
          </button>
        ))}
        {timeline.rows.length > 6 && <span className="px-2 py-1 text-xs text-faint">and {timeline.rows.length - 6} more on the grid</span>}
      </div>
    </Card>
  );
}

const DAY_COLS: { key: keyof Forecast["days"][number]; label: string; unit: string }[] = [
  { key: "gust_mph", label: "Gust", unit: " mph" }, { key: "thunder_pct", label: "Thunder", unit: "%" }, { key: "rain_in", label: "Rain", unit: " in" }, { key: "heat_index_f", label: "Heat idx", unit: "°F" },
];

// seven days at a site against the stop rules: quiet days are green, days with a note say why
export function ForecastCard({ forecast }: { forecast: Forecast }) {
  const busy = forecast.days.filter((d) => d.notes.length);
  return (
    <Card icon={<CloudSun size={15} />} title={`Forecast: ${forecast.site}`} sub={`${forecast.near ? `near ${forecast.near} · ` : ""}${forecast.source}`}>
      <Lead>{busy.length ? `${plural(busy.length, "day")} of the next seven carry a work note: ${busy.map((d) => d.dow).join(", ")}.` : "A quiet week: no day of the next seven trips a work rule."}</Lead>
      <Drawer title="Seven days" summary={forecast.days.map((d) => `${d.dow} ${d.high_f ?? "–"}°`).join(" · ")} defaultOpen={busy.length > 0}>
      <div className="overflow-x-auto">
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
      {busy.length > 0 && <ul className="flex flex-col gap-0.5 text-[11px] text-muted">{busy.map((d) => <li key={d.date}><b>{d.dow}</b>: {d.notes.join(", ")}</li>)}</ul>}
      </Drawer>
      <Note>Fetched {forecast.fetched_at.slice(0, 16).replace("T", " ")} UTC. An assessment of the week, not a work order.</Note>
    </Card>
  );
}

// a drive between two places, drawn on the map
export function RouteCard({ route, onShowRoute }: { route: Route } & CardProps) {
  return (
    <Card icon={<RouteIcon size={15} />} title={`${route.from} to ${route.to}`} sub={route.source}
      right={<Pill primary onClick={() => onShowRoute?.(route)} icon={<MapPinned size={12} />}>On map</Pill>}>
      <StatRow items={route.drive_min != null
        ? [{ label: "Drive", value: `${Math.round(route.drive_min)} min` }, { label: "By road", value: `${route.road_mi} mi` }, { label: "Straight line", value: `${route.straight_mi} mi` }]
        : [{ label: "Straight line", value: `${route.straight_mi} mi` }, { label: "By road", value: "n/a", note: "no route found" }]} />
      {route.note && <Note>{route.note}</Note>}
    </Card>
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
    <Card icon={<DownloadIcon size={15} />} title={download.filename} sub={<Row><Chip>{download.format.toUpperCase()}</Chip><span>{download.kind} · {kb(download.size)}{filters ? ` · ${filters}` : ""}</span></Row>}
      right={<Pill primary onClick={save} icon={state === "done" ? <Check size={12} /> : <DownloadIcon size={12} />}>{state === "busy" ? "Saving" : state === "done" ? "Saved" : state === "err" ? "Retry" : "Save"}</Pill>} />
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
    <Card icon={<Link2 size={15} />} title={share.title} sub={<Row>{revoked ? <Chip tone="warn">Revoked</Chip> : <Chip tone="info">Anyone with the link</Chip>}<span>{share.kind} · expires {share.expires_at.slice(0, 10)}</span></Row>}>
      {!revoked && (
        <>
          <input readOnly value={url} onFocus={(e) => e.currentTarget.select()} aria-label="Share link" className="w-full rounded-full border-2 border-line bg-soft px-2.5 py-1 text-[11px]" />
          <Row>
            <Pill primary onClick={copy} icon={copied ? <Check size={12} /> : <Copy size={12} />}>{copied ? "Copied" : "Copy link"}</Pill>
            <Pill onClick={() => window.open(url, "_blank")} icon={<ExternalLink size={12} />}>Open</Pill>
            <Pill onClick={revoke} icon={<Trash2 size={12} />}>Revoke</Pill>
          </Row>
        </>
      )}
    </Card>
  );
}

// how a number was made: the formula, the inputs with where they came from, the steps, and the sources
export function ExplainCard({ explain, onOpen }: { explain: Explain } & CardProps) {
  const method = !explain.inputs.length && !explain.steps.length;
  const n = explain.inputs.length + explain.steps.length;
  return (
    <Card icon={method ? <BookOpen size={15} /> : <Sigma size={15} />} title={explain.title}
      sub={explain.opportunity_id ? <RefLink id={explain.opportunity_id} onOpen={onOpen} /> : explain.what || undefined}>
      {explain.result && <StatRow items={[{ label: "Result", value: result(explain.result), tone: "info" }]} cols={2} />}
      <p className="whitespace-pre-line text-[12px] leading-snug">{explain.formula}</p>
      {n > 0 && (
        <Drawer title="How it was worked out" summary={`${explain.inputs.length} input${explain.inputs.length === 1 ? "" : "s"} · ${explain.steps.length} step${explain.steps.length === 1 ? "" : "s"}`}>
          {explain.inputs.length > 0 && (
            <table className="w-full text-[11px]"><tbody>
              {explain.inputs.map((i, k) => <tr key={k} className="border-t border-line first:border-t-0"><td className="py-0.5 pr-1 text-muted">{i.label}</td><td className="py-0.5 text-right font-semibold tabular-nums">{fmt(i.value)}{i.unit ? ` ${i.unit}` : ""}</td><td className="py-0.5 pl-2 text-right text-[10px] text-faint">{i.source ?? ""}</td></tr>)}
            </tbody></table>
          )}
          {explain.steps.length > 0 && <ol className="flex list-decimal flex-col gap-0.5 pl-5 text-[11px] text-muted">{explain.steps.map((s, k) => <li key={k}>{s}</li>)}</ol>}
        </Drawer>
      )}
      {(explain.assumptions?.length ?? 0) > 0 && (
        <Drawer title="Assumptions" summary={`${explain.assumptions!.length} used${explain.assumptions!.some((a) => a.verified === false) ? " · some are proxies" : ""}`}>
          <ul className="flex flex-col gap-0.5 text-[11px] text-muted">{explain.assumptions!.map((a) => <li key={a.key}>{a.label}: <b>{result(a)}</b>{a.verified === false ? <Chip tone="amber">proxy</Chip> : null}{a.source ? ` · ${a.source}${a.page ? `, p. ${a.page}` : ""}` : ""}</li>)}</ul>
        </Drawer>
      )}
      {explain.sources.length > 0 && <Row>{explain.sources.map((s) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="rounded-full bg-soft px-2 py-0.5 text-[10px] text-muted hover:text-ink">{s.title}</a>)}</Row>}
    </Card>
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
