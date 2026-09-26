import { useMemo } from "react";
import { usd } from "../data";

// shared shapes and helpers for the plan cards, the timeline and the plan panel
export type Horizon = "quarter" | "year" | "window";
export type Range = { low: number; high: number };
export type Verdict = "strong" | "possible" | "unknown" | "unlikely";
export type Item = {
  id: string; opportunity_id: number; partner: string; partner_name: string; partner_short: string; ours: string; theirs: string; our_job: string; their_job: string;
  tier: string; verdict: Verdict; feasibility: number; feasibility_source: string; narrative: string | null; savings: Range;
  window: { ours: [string, string]; theirs: [string, string]; common: [string, string]; overlap_pct: number };
  target_start: string; target_end: string; weather: { target: Range; naive: Range; avoided: Range; days: Range; naive_window: [string, string] };
  hazard_strip: Record<string, number>; action: "send request" | "follow up" | "wait"; action_reason: string; request_id: number | null;
  news: { title: string; impact: string; url?: string }[]; risks: string[]; conflicts: string[]; state: "proposed" | "accepted" | "skipped"; note: string;
  goal_id: number | null; passed?: boolean; rank: number;
};
export type Totals = {
  savings: Range; weather_avoided: Range; verdicts: Record<Verdict, number>; selected: number; considered: number; skipped: Record<string, number>;
  period: [string, string] | null; conflicts: number; passed: number; actions: Record<string, number>; note: string;
};
export type Plan = { id: number; horizon: Horizon; version: number; items: Item[]; totals: Totals; status: string; created_at: string };
export type Explain = {
  chosen_because: { feasibility: string; feasibility_score: number; feasibility_source: string; savings_usd: Range; rank: number; windows_overlap_pct: number };
  months_because: { target: [string, string]; weather_cost_usd: Range; instead_of: [string, string]; its_weather_cost_usd: Range; avoided_usd: Range; affected_days: Range; common_window: [string, string] };
  action: string; action_reason: string; risks: string[]; news: { title: string; impact: string; url?: string }[]; conflicts: string[]; method: string;
};
export type ItemPatch = Partial<Pick<Item, "state" | "target_start" | "target_end" | "note">>;

export const HORIZONS: [Horizon, string][] = [["quarter", "Next quarter"], ["year", "Next year"], ["window", "Whole window"]];
export const horizonLabel = (h: string | undefined) => (HORIZONS.find(([k]) => k === h)?.[1] ?? "Next quarter").toLowerCase();
export const VERDICT: Record<Verdict, { label: string; color: string; bg: string }> = {
  strong: { label: "Strong", color: "#12a36b", bg: "#dff6ec" }, possible: { label: "Possible", color: "#b8860b", bg: "#fff3d9" },
  unknown: { label: "Unknown", color: "#5e6a8a", bg: "#eef1f6" }, unlikely: { label: "Unlikely", color: "#8a94b0", bg: "#e6e9ef" },
};
export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const money = (r: Range) => (r.low === r.high ? usd(r.low) : `${usd(r.low)} to ${usd(r.high)}`);
export const mon = (s: string) => { const d = new Date(`${s.slice(0, 10)}T12:00:00`); return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
export const first = (s: string) => new Date(`${s.slice(0, 7)}-01T12:00:00`);
export const addMonths = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth() + n, 1, 12);
export const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
export const lastDay = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0, 12);
export const iso = (d: Date) => `${key(d)}-${String(d.getDate()).padStart(2, "0")}`;
export const pending = (it: Item) => it.state !== "skipped" && !it.goal_id && !it.request_id;  // still up to us
export const accepted = (p: Plan) => p.items.filter((i) => i.state === "accepted" && !i.goal_id && !i.request_id);
export const planLine = (p: Plan, horizon?: string) =>
  p.items.length ? `Plan for ${horizonLabel(horizon ?? p.horizon)}: ${p.items.length} pair${p.items.length === 1 ? "" : "s"}, ${money(p.totals.savings)} in savings.${p.totals.note ? " I had to look further out." : ""}`
    : "No pairs to plan in this horizon. Try a longer one.";

export function VerdictChip({ v }: { v: Verdict }) {
  const c = VERDICT[v];
  return <span className="rounded-full px-2 py-0.5 text-xs font-semibold" style={{ background: c.bg, color: c.color }}>{c.label}</span>;
}

export function StateChip({ s }: { s: Item["state"] }) {
  if (s === "accepted") return <span className="rounded-full bg-save-soft px-2 py-0.5 text-xs font-semibold text-save">Accepted</span>;
  if (s === "skipped") return <span className="rounded-full bg-soft px-2 py-0.5 text-xs font-semibold text-muted">Skipped</span>;
  return null;
}

export function MonthPicker({ item, onChange }: { item: Item; onChange: (start: string, end: string) => void }) {
  const opts = useMemo(() => {  // any month inside the common window
    const out: Date[] = [];
    for (let d = first(item.window.common[0]); d <= first(item.window.common[1]) && out.length < 60; d = addMonths(d, 1)) out.push(d);
    return out;
  }, [item.window.common]);
  const s = key(first(item.target_start)), e = key(first(item.target_end));
  const pick = (ns: string, ne: string) => {
    const a = new Date(`${ns}-01T12:00:00`), b = new Date(`${ne}-01T12:00:00`);
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    onChange(iso(lo), iso(lastDay(hi)));
  };
  const sel = "rounded-full border-2 border-line bg-white px-2 py-0.5 text-xs font-semibold outline-none focus:border-pen";
  return (
    <span className="flex items-center gap-1 text-xs text-muted">
      <select value={s} onChange={(ev) => pick(ev.target.value, e)} className={sel} aria-label="Start month">{opts.map((d) => <option key={key(d)} value={key(d)}>{mon(iso(d))}</option>)}</select>
      to
      <select value={e} onChange={(ev) => pick(s, ev.target.value)} className={sel} aria-label="End month">{opts.map((d) => <option key={key(d)} value={key(d)}>{mon(iso(d))}</option>)}</select>
    </span>
  );
}

// the months the timeline shows: the plan's period, or the span of the chosen months for whole windows
export function axis(plan: Plan): Date[] {
  const p = plan.totals.period;
  let start = p ? first(p[0]) : null, end = p ? first(p[1]) : null;
  if (!start || !end) {
    const starts = plan.items.map((i) => first(i.target_start).getTime()), ends = plan.items.map((i) => first(i.target_end).getTime());
    if (!starts.length) { const t = new Date(); return Array.from({ length: 12 }, (_, k) => addMonths(new Date(t.getFullYear(), t.getMonth(), 1, 12), k)); }
    start = new Date(Math.min(...starts)); end = new Date(Math.max(...ends));
  }
  const out: Date[] = [];
  for (let d = start; d <= end && out.length < 36; d = addMonths(d, 1)) out.push(d);
  return out;
}
