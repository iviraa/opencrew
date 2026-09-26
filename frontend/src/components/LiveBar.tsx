import { CloudLightning, Pause, Play, RefreshCw, Wind } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { LiveFrame } from "../api";
import { INCIDENT_KIND } from "./IncidentCard";
import { Bubble } from "./ui-plan";

type Props = {
  frame: LiveFrame | null; scenario: "none" | "helene"; at: number | null; onAt: (t: number | null) => void; loading: boolean;
  onScenario: (s: "none" | "helene") => void; onPoll: () => Promise<unknown>; onIncident: (id: number) => void;
};

const HOUR = 3600e3;
const LANDFALL = Date.parse("2024-09-27T03:10:00Z");
const et = (t: number | string, withDay = true) => new Date(t).toLocaleString("en-US", {
  timeZone: "America/New_York", ...(withDay ? { weekday: "short" } : {}), month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function rel(t: number) {
  const h = Math.round((t - LANDFALL) / HOUR);
  if (h === 0) return "Landfall";
  const n = Math.abs(h);
  return `${n} ${n === 1 ? "hour" : "hours"} ${h > 0 ? "after" : "before"} landfall`;
}

function ago(t: number, now: number) {
  const h = Math.round((now - t) / HOUR);
  if (h < 1) return "Now";
  if (h < 48) return `${h} ${h === 1 ? "hour" : "hours"} ago`;
  return `${Math.round(h / 24)} days ago`;
}

export default function LiveBar({ frame, scenario, at, onAt, loading, onScenario, onPoll, onIncident }: Props) {
  const [playing, setPlaying] = useState(false);
  const [polling, setPolling] = useState(false);
  const helene = scenario === "helene";
  const [start, end] = frame ? frame.range.map((x) => Date.parse(x)) : [Date.now() - 30 * 24 * HOUR, Date.now()];
  const value = at ?? end;
  const live = !helene && at == null;
  const valueRef = useRef(value);
  valueRef.current = value;

  useEffect(() => { setPlaying(false); }, [scenario]);
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const next = valueRef.current + 3 * HOUR;
      if (next > end) { setPlaying(false); if (!helene) onAt(null); return; }
      onAt(next);
    }, 900);
    return () => clearInterval(id);
  }, [playing, end, onAt, helene]);

  const incidents = [...(frame?.incidents?.features ?? [])].sort((a, b) =>
    Number(b.properties?.verified) - Number(a.properties?.verified) || (b.properties?.confidence ?? 0) - (a.properties?.confidence ?? 0));
  const verified = incidents.filter((f) => f.properties?.verified).length;
  const alerts = frame?.warnings.features.length ?? 0;
  const news = frame?.news.features.length ?? 0;
  const work = frame?.active_phases.features.length ?? 0;
  const risks = frame?.wind_risks ?? [];
  const poll = () => { setPolling(true); onPoll().finally(() => setPolling(false)); };
  const landfallPct = ((LANDFALL - start) / (end - start)) * 100;

  return (
    <div className="thin-scroll flex h-full flex-col overflow-y-auto px-5 py-3">
      <div className="flex flex-wrap items-center gap-3">
        {!live && (
          <button onClick={() => { if (value >= end) onAt(start); setPlaying((p) => !p); }} aria-label={playing ? "Pause" : "Play"}
            className={`grid h-11 w-11 shrink-0 place-items-center rounded-full text-white shadow-float transition hover:brightness-105 ${helene ? "bg-gpc" : "bg-ink"}`}>
            {playing ? <Pause size={22} fill="currentColor" /> : <Play size={22} fill="currentColor" className="ml-0.5" />}
          </button>
        )}
        {live && (
          <span className="inline-flex items-center gap-2 rounded-full bg-gpc-soft px-3 py-1.5 text-[14px] font-semibold text-gpc">
            <span className="live-dot h-2.5 w-2.5 rounded-full bg-gpc" /> Live
          </span>
        )}
        <div className="min-w-0">
          <div className="display text-[20px] font-semibold leading-tight">
            {helene ? rel(value) : live ? "Right now" : ago(value, end)}
          </div>
          <div className="text-[13px] text-muted">{helene ? `${et(value)} ET, Hurricane Helene, September 2024` : `${et(value)} ET`}</div>
        </div>
        {(loading || !frame) && <span className="text-[13px] text-faint" aria-live="polite">{frame ? "Updating…" : "Loading the map…"}</span>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {!helene && !live && (
            <button onClick={() => { setPlaying(false); onAt(null); }} className="rounded-full bg-gpc px-4 py-2 text-[14px] font-semibold text-white">Back to live</button>
          )}
          {live && (
            <button onClick={poll} disabled={polling}
              className="inline-flex items-center gap-2 rounded-full bg-soft px-4 py-2 text-[14px] font-semibold ring-1 ring-line hover:bg-surface disabled:opacity-50">
              <RefreshCw size={15} className={polling ? "animate-spin" : ""} /> {polling ? "Checking weather and news…" : "Refresh now"}
            </button>
          )}
          {helene
            ? <button onClick={() => onScenario("none")} className="rounded-full bg-gpc px-4 py-2 text-[14px] font-semibold text-white">Back to live</button>
            : <button onClick={() => onScenario("helene")}
                className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-[14px] font-semibold text-white hover:bg-[#2a3563]">
                <CloudLightning size={15} /> Play Hurricane Helene (Sept 2024)
              </button>}
        </div>
      </div>

      <div className="mt-2">
        <input type="range" min={start} max={end} step={HOUR} value={value} aria-label={helene ? "Scenario time" : "Map time"}
          onChange={(e) => { setPlaying(false); const t = Number(e.target.value); onAt(!helene && t >= end - HOUR ? null : t); }}
          className={`w-full ${helene ? "accent-[#ff5d5d]" : "accent-[#1b2447]"}`} />
        <div className="relative h-4 text-[12px] text-faint">
          <span className="absolute left-0">{helene ? "3 days before" : "30 days ago"}</span>
          {helene && <span className="absolute -translate-x-1/2 font-semibold text-gpc" style={{ left: `${landfallPct}%` }}>landfall</span>}
          <span className="absolute right-0">{helene ? "1 day after" : "Now"}</span>
        </div>
      </div>

      <div className="mt-2 grid grid-cols-4 gap-2">
        <Bubble compact label="Weather alerts" value={alerts} sub={alerts ? "active at this time" : "none active"} />
        <Bubble compact tone="gpc" label="Incidents" value={incidents.length} sub={`${verified} verified, ${incidents.length - verified} need a second source`} />
        <Bubble compact tone="desc" label="News near sites" value={news} sub={news ? "tap a pin to read" : "nothing nearby"} />
        <Bubble compact tone="save" label="Work sites active" value={work} sub={risks.length ? `${risks.length} wind warnings this week` : "construction phases under way"} />
      </div>

      <div className="mt-2 flex shrink-0 gap-2 overflow-x-auto pb-1">
        {risks.map((r) => (
          <span key={`${r.job_id}${r.day}`} title={r.alert} className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-warn-soft px-3.5 text-[13px] font-semibold text-warn">
            <Wind size={14} /> {r.site}: {r.gust_mph} mph gusts
          </span>
        ))}
        {incidents.length === 0 && risks.length === 0 && (
          <span className="text-[13px] text-muted">No incidents {helene ? "yet at this point in the storm" : "in the 24 hours before this time"}.</span>
        )}
        {incidents.slice(0, 30).map((f) => {
          const p = f.properties!;
          const k = INCIDENT_KIND[p.kind] ?? { label: p.kind, color: "#8a94b0" };
          return (
            <button key={p.id} onClick={() => onIncident(Number(p.id))} title={`${k.label}, ${p.where_text}, confidence ${Math.round(p.confidence * 100)}%`}
              className="flex h-9 shrink-0 items-center gap-2 rounded-full bg-soft px-3.5 text-[13px] ring-1 ring-line transition hover:bg-surface">
              <span className="h-3 w-3 rounded-full" style={p.verified ? { background: k.color } : { border: `2.5px solid ${k.color}` }} />
              <span className="font-semibold">{k.label}</span>
              <span className="max-w-[160px] truncate text-muted">{p.where_text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
