import { MONTHS } from "../plan/types";
import { bare, dateShort, signedPct, signedUnit, usd, withUnit } from "../ui/format";
import { changeLabel, type Change } from "./changes";
import { direction, unitOf, type Comparison, type Delta, type Finding } from "./types";

// what one applied change did, as the start of a sentence
export function describeChange(c: Change): string {
  const p = c.params ?? {};
  const id = p.opportunity_id ?? p.overlap_id;
  const n = (v: unknown) => Number(v);
  switch (c.kind) {
    case "shift_window": { const m = n(p.months); return `Shifting ${id ? `overlap #${id}` : "our window"} by ${m > 0 ? "+" : ""}${m} month${Math.abs(m) === 1 ? "" : "s"}`; }
    case "assumption": return `Changing ${String(p.name ?? "an assumption").replace(/_/g, " ")} by ${n(p.pct) > 0 ? "+" : ""}${n(p.pct)}%`;
    case "exclude_partner": return `Excluding ${p.partner || "one partner"}`;
    case "add_project": return `Adding a ${p.kv ? `${p.kv} kV ` : ""}project`;
    case "cancel_project": return `Cancelling ${p.side === "theirs" ? "their" : "our"} project on #${id ?? "?"}`;
    case "rule": { const ms = Array.isArray(p.months) ? (p.months as number[]).map((m) => MONTHS[m - 1]).filter(Boolean).join(", ") : ""; return `Ruling out ${p.phase ?? "work"}${ms ? ` in ${ms}` : ""}${p.where && p.where !== "everywhere" ? ` on the ${p.where}` : ""}`; }
    case "capacity": { const c2 = n(p.crews); return `${c2 >= 0 ? "Adding" : "Removing"} ${Math.abs(c2)} crew${Math.abs(c2) === 1 ? "" : "s"} in ${p.quarter ?? ""} ${p.year ?? ""}`.replace(/\s+/g, " ").trim(); }
    case "budget": return n(p.target_savings_usd) > 0 ? `Targeting ${usd(n(p.target_savings_usd))} in savings` : `Capping spend at ${usd(n(p.cap_usd))}`;
    case "storm": return `A category ${p.category ?? "3"} storm${p.place && typeof p.place === "string" ? ` at ${p.place}` : ""}${p.date ? ` on ${dateShort(String(p.date))}` : ""}`;
    case "replay_year": return `Replaying the weather of ${p.year}`;
    default: return changeLabel(c);
  }
}

const AND = (parts: string[]) => (parts.length <= 1 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`);
const lower = (s: string, i: number) => (i === 0 ? s : s[0].toLowerCase() + s.slice(1));

// the numeric deltas worth talking about: dollars first, then whatever moved most
export function movers(deltas: Delta[]): Delta[] {
  const weight = (d: Delta) => (unitOf(d.metric, d.unit) === "USD" ? 2 : 1) * Math.abs(d.pct ?? 0);
  const ranked = deltas.filter((d) => typeof d.delta === "number" && d.delta !== 0 && typeof d.base === "number" && typeof d.scenario === "number")
    .sort((a, b) => weight(b) - weight(a) || Math.abs(Number(b.delta)) - Math.abs(Number(a.delta)));
  const seen = new Set<string>();  // a low/high pair counts as one mover
  return ranked.filter((d) => { const key = d.label.replace(/\s*\((low|high)\)\s*$/i, "").toLowerCase(); if (seen.has(key)) return false; seen.add(key); return true; });
}

const clause = (d: Delta) => {
  const u = unitOf(d.metric, d.unit), up = Number(d.delta) > 0, good = direction(d.metric, d.delta) === "good";
  const verb = up ? "raises" : good ? "cuts" : "lowers";
  const tail = `(${signedUnit(Number(d.delta), u)}${u !== "%" && d.pct != null && d.pct !== 0 ? `, ${signedPct(d.pct)}` : ""})`;
  return `${verb} ${d.label.toLowerCase()} from ${bare(d.base, u)} to ${withUnit(d.scenario as number, u)} ${tail}`;
};

// one or two sentences that say what the experiment found, from its own numbers only
export function findingSentence(f: Finding, stack: Change[]): string {
  const subject = AND(stack.map(describeChange).map(lower));
  const top = movers(f.deltas).slice(0, 2);
  const flips = f.deltas.filter((d) => typeof d.delta !== "number" && d.base !== d.scenario).slice(0, 1);
  if (!top.length && !flips.length) return `${subject} leaves the numbers where they are.`;
  const parts = [...top.map(clause), ...flips.map((d) => `moves ${d.label.toLowerCase()} from ${d.base} to ${d.scenario}`)];
  return `${subject} ${AND(parts)}.`;
}

export function compareSentence(c: Comparison): string {
  const name = (x: Finding | number) => (typeof x === "number" ? `finding #${x}` : x.title);
  const top = movers(c.deltas).slice(0, 2);
  if (!top.length) return `${name(c.b)} and ${name(c.a)} land on the same numbers.`;
  const parts = top.map((d) => { const u = unitOf(d.metric, d.unit); return `${d.label.toLowerCase()} ${signedUnit(Number(d.delta), u)}${d.pct != null && d.pct !== 0 ? ` (${signedPct(d.pct)})` : ""}`; });
  return `Against ${name(c.a)}, ${name(c.b)} changes ${AND(parts)}.`;
}
