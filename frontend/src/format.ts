import type { Tier } from "./api";

export const TIER_COLOR: Record<Tier, string> = { crossing: "#7c3aed", land: "#c026d3", site: "#0891b2", crew: "#64748b" };

export const TIER_LABEL: Record<Tier, string> = { crossing: "Crossing", land: "Shared land", site: "Shared site", crew: "Shared crew" };

export const STATUSES = ["not_contacted", "drafted", "sent", "replied", "call_scheduled", "agreed", "declined"];

export const QUALITY_LABEL: Record<string, string> = {
  straight_line: "straight line (approx route)",
  partial_point: "one endpoint located",
  matched_point: "substation located",
  existing_path: "follows existing line",
  exact: "exact route",
  manual: "placed by hand",
};

export const FLAG_LABEL: Record<string, string> = {
  over_45_min_drive: "Over 45 min by road",
  hurricane_season_high_risk: "Hurricane season, high risk",
  tie_line: "Interstate tie line",
  shared_endpoint: "Shared substation",
  shared_wetland: "Shared wetland",
};

export const BASIS_LABEL: Record<string, string> = {
  filed: "start date from filing",
  spend_years: "start from budget years",
  default_duration: "start derived from typical duration",
};

export const miles = (m: number) => `${(m / 1609.344).toFixed(m < 16093 ? 1 : 0)} mi`;
export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const title = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
export const monthYear = (iso: string) => new Date(iso).toLocaleDateString("en-US", { month: "short", year: "numeric" });

export function usd(n: number) {
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}k`;
  return `$${Math.round(n)}`;
}
