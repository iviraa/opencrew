import { useEffect, useRef, useState } from "react";
import type { StormFrame } from "../api";
import { INCIDENT_KIND } from "./IncidentCard";

type Props = {
  frame: StormFrame | null; at: number; onAt: (t: number) => void; start: number; end: number; landfall: number; loading: boolean;
  live: boolean; onLive: (live: boolean) => void; onPoll: () => Promise<unknown>; onIncident: (id: number) => void;
};

const STEP_MS = 3 * 3600e3;

function rel(t: number, landfall: number) {
  const h = Math.round((t - landfall) / 3600e3);
  return h === 0 ? "Landfall" : `T${h > 0 ? "+" : "−"}${Math.abs(h)}h`;
}

const et = (t: number | string) => new Date(t).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

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
  const cone = frame?.cone.features[0]?.properties?.payload;
  const incidents = [...(frame?.incidents?.features ?? [])].sort((a, b) =>
    Number(b.properties?.verified) - Number(a.properties?.verified) || (b.properties?.confidence ?? 0) - (a.properties?.confidence ?? 0));
  const verified = incidents.filter((f) => f.properties?.verified).length;

  const poll = () => { setPolling(true); onPoll().finally(() => setPolling(false)); };

  return (
    <div className="flex h-full flex-col bg-white px-4 py-2.5">
      <div className="flex items-center gap-3">
        <div className="flex rounded-md bg-slate-100 p-0.5 text-xs">
          {[false, true].map((v) => (
            <button key={String(v)} onClick={() => { setPlaying(false); onLive(v); }}
              className={`rounded px-2 py-1 font-medium ${live === v ? "bg-white shadow-sm" : "text-slate-500"}`}>{v ? "Live" : "Helene replay"}</button>
          ))}
        </div>
        {live ? (
          <>
            <div className="text-sm font-semibold">Last 24 hours</div>
            <div className="text-xs text-slate-500">as of {et(Date.now())} ET</div>
            <button onClick={poll} disabled={polling} className="rounded-md bg-slate-900 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50">
              {polling ? "Polling NWS, SPC, news…" : "Poll now"}
            </button>
          </>
        ) : (
          <>
            <button onClick={() => { if (at >= end) onAt(start); setPlaying((p) => !p); }}
              className="w-16 rounded-md bg-slate-900 px-3 py-1 text-sm font-semibold text-white">{playing ? "Pause" : "Play"}</button>
            <div className="w-20 text-sm font-semibold">{rel(at, landfall)}</div>
            <div className="text-xs text-slate-500">{et(at)} ET</div>
          </>
        )}
        {(loading || !frame) && <div className="text-[11px] text-slate-400">{frame ? "updating…" : "loading storm data…"}</div>}
        <div className="ml-auto text-[11px] text-slate-400">
          {live ? "api.weather.gov alerts, SPC and IEM reports, GDELT news" : "Hurricane Helene, Sept 2024 · NHC, NWS, SPC archives and GDELT news"}
        </div>
      </div>
      {!live && (
        <>
          <input type="range" min={start} max={end} step={STEP_MS / 3} value={at} onChange={(e) => { setPlaying(false); onAt(Number(e.target.value)); }}
            className="mt-1.5 w-full accent-rose-600" />
          <div className="relative h-3 text-[10px] text-slate-400">
            <span className="absolute left-0">T−72h</span>
            <span className="absolute -translate-x-1/2 font-semibold text-rose-600" style={{ left: `${((landfall - start) / (end - start)) * 100}%` }}>landfall</span>
            <span className="absolute right-0">T+24h</span>
          </div>
        </>
      )}
      <div className="mt-2 grid grid-cols-5 gap-2 text-xs">
        {live
          ? <Stat label="Active NWS warnings" value={String(frame?.warnings.features.length ?? 0)} />
          : <Stat label="Forecast cone" value={cone ? `Advisory ${cone.advisory}` : "none yet"} />}
        {live
          ? <Stat label="Storm reports (24 h)" value={String(reports.length)} />
          : <Stat label="Substations in cone" value={`DESC ${frame?.exposure.desc ?? 0} · GPC ${frame?.exposure.gpc ?? 0}`} />}
        {!live && <Stat label="Damage reports so far" value={`${reports.length} (${power} mention power)`} />}
        <Stat label="Incidents" value={`${incidents.length} · ${verified} verified · ${incidents.length - verified} unverified`} />
        <Stat label="Shared staging points" value={staging.length ? staging.map((f) => `DESC ${f.properties?.desc_n} + GPC ${f.properties?.gpc_n} sites`).join("; ") : "none yet"} />
      </div>
      <div className="mt-2 flex min-h-0 flex-1 gap-1.5 overflow-x-auto pb-1">
        {incidents.length === 0 && <span className="text-[11px] text-slate-400">No incidents {live ? "in the last 24 hours" : "yet at this time"}.</span>}
        {incidents.slice(0, 30).map((f) => {
          const p = f.properties!;
          const k = INCIDENT_KIND[p.kind] ?? { label: p.kind, color: "#64748b" };
          return (
            <button key={p.id} onClick={() => onIncident(Number(p.id))} title={`${k.label} · ${p.where_text} · confidence ${Math.round(p.confidence * 100)}%`}
              className="flex h-7 shrink-0 items-center gap-1.5 rounded-full bg-slate-50 px-2.5 text-[11px] ring-1 ring-slate-200 hover:bg-slate-100">
              <span className="h-2.5 w-2.5 rounded-full" style={p.verified ? { background: k.color } : { border: `2px solid ${k.color}` }} />
              <span className="font-medium">{k.label}</span>
              <span className="max-w-[140px] truncate text-slate-500">{p.where_text}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-1.5 ring-1 ring-slate-200">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="truncate font-semibold" title={value}>{value}</div>
    </div>
  );
}
