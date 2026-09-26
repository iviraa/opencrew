import type { Finding, Knob } from "./types";

// one applied change in a scenario; a finding of kind "compose" stacks several
export type Change = { kind: string; params: Record<string, unknown>; label?: string };

export type ChangeKind = { kind: string; label: string; knobs: Knob[] };
export const CHANGE_KINDS: ChangeKind[] = [
  { kind: "shift_window", label: "Shift window", knobs: [
    { name: "opportunity_id", type: "number", value: null, label: "Overlap #" }, { name: "months", type: "month_shift", value: 3, min: -6, max: 6, label: "Shift ours by" }] },
  { kind: "assumption", label: "Change assumption", knobs: [
    { name: "name", type: "select", value: "crew_day_usd", options: ["crew_day_usd", "crane_standby_usd_day", "storm_rate_multiplier", "drive_limit_min"], label: "Assumption" },
    { name: "pct", type: "number", value: 20, min: -90, max: 300, label: "Change by %" }] },
  { kind: "exclude_partner", label: "Exclude partner", knobs: [{ name: "partner", type: "select", value: "", options: [], label: "Partner" }] },
  { kind: "add_project", label: "Add project", knobs: [
    { name: "kv", type: "select", value: 230, options: [115, 138, 161, 230, 345, 500], label: "kV" }, { name: "from", type: "place", value: null, label: "From" },
    { name: "to", type: "place", value: null, label: "To" }, { name: "start", type: "date", value: "", label: "Start" }, { name: "end", type: "date", value: "", label: "In service" }] },
  { kind: "cancel_project", label: "Cancel project", knobs: [{ name: "opportunity_id", type: "number", value: null, label: "Overlap #" }, { name: "side", type: "select", value: "ours", options: ["ours", "theirs"], label: "Which project" }] },
  { kind: "rule", label: "Rule", knobs: [
    { name: "phase", type: "select", value: "stringing", options: ["stringing", "crane lifts", "clearing", "all work"], label: "No" },
    { name: "months", type: "months", value: [8, 9], label: "In" }, { name: "where", type: "select", value: "coast", options: ["coast", "everywhere"], label: "Where" }] },
  { kind: "capacity", label: "Capacity", knobs: [
    { name: "crews", type: "number", value: 1, min: -3, max: 5, label: "Extra crews" }, { name: "quarter", type: "select", value: "Q2", options: ["Q1", "Q2", "Q3", "Q4"], label: "Quarter" },
    { name: "year", type: "number", value: new Date().getFullYear() + 1, label: "Year" }] },
  { kind: "budget", label: "Budget", knobs: [{ name: "cap_usd", type: "number", value: 500000, min: 0, label: "Cap spend at $" }, { name: "target_savings_usd", type: "number", value: 0, min: 0, label: "Or find savings of $" }] },
  { kind: "storm", label: "Storm", knobs: [
    { name: "place", type: "place", value: null, label: "Landfall" }, { name: "category", type: "select", value: 3, options: [1, 2, 3, 4, 5], label: "Category" },
    { name: "date", type: "date", value: "", label: "Date" }, { name: "radius_km", type: "number", value: 80, min: 10, max: 400, label: "Radius km" }] },
  { kind: "replay_year", label: "Replay a year", knobs: [{ name: "year", type: "select", value: 2024, options: [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025], label: "Weather of" }] },
];
export const kindLabel = (k: string) => CHANGE_KINDS.find((c) => c.kind === k)?.label ?? k.replace(/_/g, " ");

// what a finding applies: its own change, or the stack inside a composed one
export const changesOf = (f: Finding): Change[] => {
  if (f.kind === "compose" && Array.isArray(f.params.changes)) return f.params.changes as Change[];
  return [{ kind: f.kind, params: f.params }];
};

const brief = (v: unknown): string => {
  if (v == null || v === "") return "";
  if (typeof v === "object") { const o = v as { lon?: number; lat?: number }; return o.lon != null && o.lat != null ? `${o.lat.toFixed(2)}, ${o.lon.toFixed(2)}` : Array.isArray(v) ? v.join(",") : ""; }
  return String(v);
};
export const changeLabel = (c: Change) =>
  c.label ?? `${kindLabel(c.kind)}: ${Object.entries(c.params).filter(([k]) => !["changes", "base_finding_id"].includes(k)).map(([, v]) => brief(v)).filter(Boolean).slice(0, 3).join(" · ")}`;

// merge two stacks for "Combine": same kind and same key params count once
export const combine = (a: Change[], b: Change[]) => {
  const seen = new Set<string>(), out: Change[] = [];
  for (const c of [...a, ...b]) { const k = JSON.stringify([c.kind, c.params]); if (!seen.has(k)) { seen.add(k); out.push(c); } }
  return out;
};
