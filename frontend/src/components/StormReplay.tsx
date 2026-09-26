import { useEffect, useRef, useState } from "react";
import type { StormFrame } from "../api";

type Props = { frame: StormFrame | null; at: number; onAt: (t: number) => void; start: number; end: number; landfall: number };

const STEP_MS = 3 * 3600e3;

function rel(t: number, landfall: number) {
  const h = Math.round((t - landfall) / 3600e3);
  return h === 0 ? "Landfall" : `T${h > 0 ? "+" : "−"}${Math.abs(h)}h`;
}

export default function StormReplay({ frame, at, onAt, start, end, landfall }: Props) {
  const [playing, setPlaying] = useState(false);
  const atRef = useRef(at);
  atRef.current = at;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const next = atRef.current + STEP_MS;
      if (next > end) { setPlaying(false); return; }
      onAt(next);
    }, 900);
    return () => clearInterval(id);
  }, [playing, end, onAt]);

  const reports = frame?.reports.features ?? [];
  const power = reports.filter((f) => f.properties?.payload?.power).length;
  const staging = frame?.staging.features ?? [];
  const cone = frame?.cone.features[0]?.properties?.payload;

  return (
    <div className="flex h-full flex-col bg-white px-4 py-3">
      <div className="flex items-center gap-3">
        <button onClick={() => { if (at >= end) onAt(start); setPlaying((p) => !p); }}
          className="w-20 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white">{playing ? "Pause" : "Play"}</button>
        <div className="w-28 text-sm font-semibold">{rel(at, landfall)}</div>
        <div className="text-xs text-slate-500">
          {new Date(at).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET
        </div>
        <div className="ml-auto text-[11px] text-slate-400">Hurricane Helene, Sept 2024 · historical replay from NHC, NWS and SPC archives</div>
      </div>
      <input type="range" min={start} max={end} step={STEP_MS / 3} value={at} onChange={(e) => { setPlaying(false); onAt(Number(e.target.value)); }}
        className="mt-2 w-full accent-rose-600" />
      <div className="relative h-3 text-[10px] text-slate-400">
        <span className="absolute left-0">T−72h</span>
        <span className="absolute -translate-x-1/2 font-semibold text-rose-600" style={{ left: `${((landfall - start) / (end - start)) * 100}%` }}>landfall</span>
        <span className="absolute right-0">T+24h</span>
      </div>
      <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
        <Stat label="Forecast cone" value={cone ? `Advisory ${cone.advisory}` : "none yet"} />
        <Stat label="Substations in cone" value={`DESC ${frame?.exposure.desc ?? 0} · GPC ${frame?.exposure.gpc ?? 0}`} />
        <Stat label="Damage reports so far" value={`${reports.length} (${power} mention power)`} />
        <Stat label="Shared staging points" value={staging.length ? staging.map((f) => `DESC ${f.properties?.desc_n} + GPC ${f.properties?.gpc_n} sites`).join("; ") : "none yet"} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}
