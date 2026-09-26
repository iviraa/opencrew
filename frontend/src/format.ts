import type { Tier } from "./api";

export const TIER_COLOR: Record<Tier, string> = { crossing: "#7c4dff", land: "#ff4fa3", site: "#00b8a9", crew: "#ffb020" };
export const TIER_SOFT: Record<Tier, string> = { crossing: "#efe9ff", land: "#ffe6f2", site: "#dcf7f4", crew: "#fff3d9" };
export const TIER_INK: Record<Tier, string> = { crossing: "#5a2fe0", land: "#c81d73", site: "#00766c", crew: "#9a5b00" };  // readable text on the soft fill
export const FAR_COLOR = "#a3adc7";
export const DESC_COLOR = "#2f6bff";
export const GPC_COLOR = "#ff5d5d";

export const TIER_LABEL: Record<Tier, string> = { crossing: "Lines cross", land: "Share land", site: "Share a yard", crew: "Share crews" };
export const TIER_HINT: Record<Tier, string> = {
  crossing: "The two projects touch, so outages and crossing work must be planned together.",
  land: "Under a mile apart: they can share right-of-way, access roads and permits.",
  site: "Under 5 miles apart: one staging yard can serve both.",
  crew: "Under 25 miles apart: crews and equipment can move between them.",
};

export const tooFar = (driveMin: number | null | undefined) => driveMin != null && driveMin > 45;

export const STATUSES = ["not_contacted", "drafted", "sent", "replied", "call_scheduled", "agreed", "declined"];

export const QUALITY_LABEL: Record<string, string> = {
  straight_line: "straight line (approx route)",
  partial_point: "one endpoint located",
  approx_area: "approximate area, town only",
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

export const NEWS_TOPIC: Record<"damage" | "outage" | "work" | "other", { label: string; color: string }> = {
  damage: { label: "power damage", color: "#e03131" },
  outage: { label: "outages", color: "#f08c00" },
  work: { label: "construction and utility work", color: "#2f6bff" },
  other: { label: "other", color: "#8a94b0" },
};
