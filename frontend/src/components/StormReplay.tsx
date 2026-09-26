import { Pause, Play, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { StormFrame } from "../api";
import { INCIDENT_KIND } from "./IncidentCard";
import { Bubble, Segmented } from "./ui-plan";

type Props = {
  frame: StormFrame | null; at: number; onAt: (t: number) => void; start: number; end: number; landfall: number; loading: boolean;
  live: boolean; onLive: (live: boolean) => void; onPoll: () => Promise<unknown>; onIncident: (id: number) => void;
};

const STEP_MS = 3 * 3600e3;

function rel(t: number, landfall: number) {
  const h = Math.round((t - landfall) / 3600e3);
  if (h === 0) return "Landfall";
  const n = Math.abs(h);
  return `${n} ${n === 1 ? "hour" : "hours"} ${h > 0 ? "after" : "before"} landfall`;
}

const et = (t: number | string) => new Date(t).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export default function StormReplay({ frame, at, onAt, start, end, landfall, loading, live, onLive, onPoll, onIncident }: Props) {
  const [playing, setPlaying] = useState(false);
  const [polling, setPolling] = useState(false);
  const atRef = useRef(at);
  atRef.current = at;

  useEffect(() => {
    if (!playing || live) return;
    const id = setInterval(() => {
      const next = atRef.current + STEP_MS;
      if (next > end) { setPlaying(false); return; }
      onAt(next);
    }, 900);
    return () => clearInterval(id);
  }, [playing, end, onAt, live]);

  const reports = frame?.reports.features ?? [];
  const power = reports.filter((f) => f.properties?.payload?.power).length;
  const staging = frame?.staging.features ?? [];
  const incidents = [...(frame?.incidents?.features ?? [])].sort((a, b) =>
    Number(b.properties?.verified) - Number(a.properties?.verified) || (b.properties?.confidence ?? 0) - (a.properties?.confidence ?? 0));
  const verified = incidents.filter((f) => f.properties?.verified).length;
  const poll = () => { setPolling(true); onPoll().finally(() => setPolling(false)); };
  const landfallPct = ((landfall - start) / (end - start)) * 100;

  return (
    <div className="thin-scroll flex h-full flex-col overflow-y-auto bg-surface px-5 py-3">
      <div className="flex flex-wrap items-center gap-4">
        {!live && (
          <button onClick={() => { if (at >= end) onAt(start); setPlaying((p) => !p); }} aria-label={playing ? "Pause" : "Play"}
            className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-gpc text-white shadow-float transition hover:brightness-105">
            {playing ? <Pause size={22} fill="currentColor" /> : <Play size={22} fill="currentColor" className="ml-0.5" />}
          </button>
        )}
        <div className="min-w-0">
          <div className="display text-[22px] font-semibold leading-tight">{live ? "The last 24 hours" : rel(at, landfall)}</div>
          <div className="text-[13px] text-muted">{live ? `As of ${et(Date.now())} ET` : `${et(at)} ET, Hurricane Helene, September 2024`}</div>
        </div>
        {(loading || !frame) && <span className="text-[13px] text-faint">{frame ? "Updating…" : "Loading storm data…"}</span>}
        <div className="ml-auto flex items-center gap-2">
          {live && (
            <button onClick={poll} disabled={polling}
              className="inline-flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-[14px] font-semibold text-white disabled:opacity-50">
              <RefreshCw size={15} className={polling ? "animate-spin" : ""} /> {polling ? "Checking weather and news…" : "Check now"}
            </button>
          )}
          <Segmented value={live ? "live" : "replay"} options={[["replay", "Helene replay"], ["live", "Live"]]}
            onChange={(v) => { setPlaying(false); onLive(v === "live"); }} />
        </div>
      </div>

      {!live && (
        <div className="mt-3">
          <input type="range" min={start} max={end} step={STEP_MS / 3} value={at} aria-label="Replay time"
            onChange={(e) => { setPlaying(false); onAt(Number(e.target.value)); }} className="w-full accent-[#ff5d5d]" />
          <div className="relative h-4 text-[12px] text-faint">
            <span className="absolute left-0">3 days before</span>
            <span className="absolute -translate-x-1/2 font-semibold text-gpc" style={{ left: `${landfallPct}%` }}>landfall</span>
            <span className="absolute right-0">1 day after</span>
          </div>
        </div>
      )}

      <div className="mt-3 grid grid-cols-3 gap-2">
        <Bubble label={live ? "Storm reports today" : "Damage reports so far"} value={reports.length.toLocaleString()} sub={live ? undefined : `${power} mention power lines`} />
        <Bubble tone="gpc" label="Incidents" value={incidents.length.toLocaleString()} sub={`${verified} verified, ${incidents.length - verified} waiting for a second source`} />
        <Bubble tone="save" label="Shared staging spots" value={staging.length}
          sub={staging.length ? `serving ${staging.map((f) => `${f.properties?.desc_n} DESC and ${f.properties?.gpc_n} GPC sites`).join("; ")}` : "none needed yet"} />
      </div>

      <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
        {incidents.length === 0 && <span className="text-[13px] text-muted">No incidents {live ? "in the last 24 hours" : "yet at this point in the storm"}.</span>}
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
