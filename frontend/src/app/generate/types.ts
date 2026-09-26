// what crewly hands over in the chat: a chart, a table or a report
export type ChartKind = "bar" | "line" | "stacked";
export type ChartSeries = { name: string; values: number[]; color?: string };
export type Chart = {
  title: string; kind: ChartKind; x: string[]; series: ChartSeries[]; unit: string; source: string; dataset: string;
  options: Record<string, unknown>;
};
export type Table = { dataset: string; filters: Record<string, unknown>; columns: string[]; rows: Record<string, unknown>[]; count: number };
export type Report = { id: number; kind: string; ref_id: string | null; title: string; sections: string[]; all_sections: string[]; created_at: string };

export const SECTION_LABEL: Record<string, string> = {
  verdict: "Verdict", factors: "Factors", conditions: "What would make it work", shifts: "Shift options",
  savings: "Savings", weather: "Weather cost", coordination: "Coordinating", now7: "Next 7 days", season: "Next season", month: "Typical month",
  totals: "Totals", items: "Pairs", risks: "Risks", brief: "Brief", feasibility: "Feasibility", cost_analysis: "Cost analysis", hazard_exposure: "Hazards",
};

export const fmt = (v: unknown, unit?: string) => {
  if (typeof v !== "number") return String(v ?? "");
  if (unit === "USD") { const a = Math.abs(v), s = v < 0 ? "-" : ""; return s + (a >= 1e6 ? `$${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `$${Math.round(a / 1e3)}k` : `$${Math.round(a)}`); }
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
};

export const download = (name: string, content: string | Blob, type = "text/plain") => {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

export const toCsv = (columns: string[], rows: Record<string, unknown>[]) => {
  const cell = (v: unknown) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [columns.join(","), ...rows.map((r) => columns.map((c) => cell(r[c])).join(","))].join("\n");
};
