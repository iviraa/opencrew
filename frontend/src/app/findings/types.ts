import { api } from "../data";
import type { Chart } from "../generate/types";
import { fmt } from "../generate/types";

// what an experiment hands back: the question, the base and scenario numbers, and the knobs to try again
export type Metric = { value: number | string; unit?: string; low?: number; high?: number; label?: string };
export type Delta = { metric: string; label: string; base: number | string; scenario: number | string; delta: number | string; pct?: number; unit?: string };
export type KnobType = "month_shift" | "number" | "select" | "date" | "place" | "months";
export type Knob = { name: string; type: KnobType; value: unknown; min?: number; max?: number; options?: (string | number)[]; label: string };
export type Finding = {
  id: number; title: string; question: string; kind: string; params: Record<string, unknown>;
  base: { metrics: Record<string, Metric> }; scenario: { metrics: Record<string, Metric> }; deltas: Delta[];
  notes: string[]; evidence: string[]; knobs: Knob[]; sources: string[]; created_at: string; chart?: Chart; starred?: boolean;
};
export type Comparison = { a: Finding | number; b: Finding | number; deltas: Delta[]; title?: string };

// metrics where a bigger number is better; anything else counts up as worse, strings stay neutral
const GOOD_UP = new Set(["overlap_pct", "feasibility_score", "savings_low", "savings_high", "plan_savings_low", "plan_savings_high", "pairs", "neighbors_with_capacity"]);
const NEUTRAL = new Set(["verdict", "worst_year", "best_year"]);
export const direction = (metric: string, delta: number | string): "good" | "bad" | "flat" => {
  if (typeof delta !== "number" || delta === 0 || NEUTRAL.has(metric)) return "flat";
  return (delta > 0) === GOOD_UP.has(metric) ? "good" : "bad";
};

export const unitOf = (metric: string, unit?: string) => unit ?? (metric.includes("savings") || metric.includes("cost") ? "USD" : metric.includes("pct") ? "%" : undefined);
export const show = (v: number | string | undefined, unit?: string) => (typeof v === "number" ? `${fmt(v, unit)}${unit === "%" ? "%" : unit && unit !== "USD" ? ` ${unit}` : ""}` : String(v ?? ""));
export const range = (m: Metric | undefined) => (!m ? "" : m.low != null && m.high != null && m.low !== m.high ? `${show(m.low, m.unit)} to ${show(m.high, m.unit)}` : show(m.value, m.unit));
export const signed = (d: number | string, unit?: string) => (typeof d === "number" ? `${d > 0 ? "+" : ""}${show(d, unit)}` : String(d));
export const headline = (f: Finding) => (f.deltas[0] ? `${f.deltas[0].label} ${signed(f.deltas[0].delta, unitOf(f.deltas[0].metric, f.deltas[0].unit))}` : f.question);

export const findings = {
  run: (kind: string, params: Record<string, unknown>) => api.send<Finding>("/api/app/experiment", "POST", { kind, params }),
  get: (id: number) => api.get<Finding>(`/api/app/finding/${id}`),
  starred: async () => {
    const r = await api.get<Finding[] | { findings: Finding[] }>("/api/app/findings?starred=1");
    return Array.isArray(r) ? r : r.findings ?? [];
  },
  star: (id: number) => api.send<Finding | { starred: boolean }>(`/api/app/finding/${id}/star`, "POST"),
  remove: (id: number) => api.send<unknown>(`/api/app/finding/${id}`, "DELETE"),
  compare: (a: number, b: number) => api.send<Comparison>("/api/app/compare", "POST", { a, b }),
};

// the place and radius a storm finding describes, when it has one
export const stormOf = (f: Finding): { lon: number; lat: number; km: number } | null => {
  const p = f.params, place = (p.place ?? p.center) as { lon?: number; lat?: number } | undefined;
  const lon = Number(place?.lon ?? p.lon), lat = Number(place?.lat ?? p.lat);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  return { lon, lat, km: Number(p.radius_km ?? p.radius ?? 80) };
};

// the overlap an experiment is about, from any of the ways the params may name it
export const overlapIdOf = (f: Finding) => {
  const raw = f.params.opportunity_id ?? f.params.overlap_id ?? f.params.id;
  const n = Number(String(raw ?? "").replace("#", ""));
  return Number.isFinite(n) && n > 0 ? n : null;
};
