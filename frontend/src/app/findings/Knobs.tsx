import { MapPin } from "lucide-react";
import { MONTHS } from "../plan/types";
import type { Knob } from "./types";

export type PickPlace = (cb: (lon: number, lat: number) => void) => void;

// one control per knob type; the value goes back to the caller to re-run the experiment
export default function KnobControl({ knob, onChange, onPickPlace, picking }: { knob: Knob; onChange: (v: unknown) => void; onPickPlace?: PickPlace; picking?: boolean }) {
  const v = knob.value;
  if (knob.type === "month_shift") {
    const n = Number(v ?? 0), min = knob.min ?? -6, max = knob.max ?? 6;
    return (
      <label className="flex items-center gap-2 text-[11px] text-muted">
        <span className="w-24 shrink-0 truncate">{knob.label}</span>
        <input type="range" min={min} max={max} step={1} value={n} onChange={(e) => onChange(Number(e.target.value))} aria-label={knob.label} className="flex-1 accent-grape" />
        <span className="w-14 text-right font-semibold text-ink">{n > 0 ? `+${n}` : n} mo</span>
      </label>
    );
  }
  if (knob.type === "number") {
    return (
      <label className="flex items-center gap-2 text-[11px] text-muted">
        <span className="w-24 shrink-0 truncate">{knob.label}</span>
        <input type="number" value={v == null ? "" : String(v)} min={knob.min} max={knob.max} aria-label={knob.label}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} className="w-24 rounded-full border-2 border-line px-2 py-0.5 text-right text-ink" />
      </label>
    );
  }
  if (knob.type === "select") {
    return (
      <label className="flex items-center gap-2 text-[11px] text-muted">
        <span className="w-24 shrink-0 truncate">{knob.label}</span>
        <select value={String(v ?? "")} aria-label={knob.label} onChange={(e) => { const raw = e.target.value; const opt = (knob.options ?? []).find((o) => String(o) === raw); onChange(opt ?? raw); }}
          className="flex-1 rounded-full border-2 border-line bg-white px-2 py-0.5 text-ink">
          {v == null || v === "" ? <option value="">Pick one</option> : null}
          {(knob.options ?? []).map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
        </select>
      </label>
    );
  }
  if (knob.type === "date") {
    return (
      <label className="flex items-center gap-2 text-[11px] text-muted">
        <span className="w-24 shrink-0 truncate">{knob.label}</span>
        <input type="date" value={String(v ?? "")} aria-label={knob.label} onChange={(e) => onChange(e.target.value)} className="flex-1 rounded-full border-2 border-line px-2 py-0.5 text-ink" />
      </label>
    );
  }
  if (knob.type === "months") {
    const on = new Set((Array.isArray(v) ? v : []).map(Number));
    return (
      <div className="flex items-center gap-2 text-[11px] text-muted">
        <span className="w-24 shrink-0 truncate">{knob.label}</span>
        <div className="flex flex-wrap gap-1">
          {MONTHS.map((m, i) => (
            <button key={m} onClick={() => { const next = new Set(on); if (next.has(i + 1)) next.delete(i + 1); else next.add(i + 1); onChange([...next].sort((a, b) => a - b)); }}
              aria-pressed={on.has(i + 1)} className={`rounded-full border-2 px-1.5 py-0.5 font-semibold ${on.has(i + 1) ? "border-pen bg-grape-soft text-grape" : "border-line text-muted"}`}>{m}</button>
          ))}
        </div>
      </div>
    );
  }
  const place = v as { lon?: number; lat?: number } | null;  // place: click the map to set it
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted">
      <span className="w-24 shrink-0 truncate">{knob.label}</span>
      <button onClick={() => onPickPlace?.((lon, lat) => onChange({ lon, lat }))} disabled={!onPickPlace}
        className={`flex items-center gap-1 rounded-full border-2 px-2 py-0.5 font-semibold ${picking ? "border-pen bg-grape-soft text-grape" : "border-line text-ink"} disabled:opacity-50`}>
        <MapPin size={12} /> {picking ? "Click the map" : place?.lat != null ? `${place.lat.toFixed(2)}, ${place.lon!.toFixed(2)}` : "Pick on map"}
      </button>
    </div>
  );
}
