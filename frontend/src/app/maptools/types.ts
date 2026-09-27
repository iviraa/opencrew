// what the map, data and explain tools hand the chat: each becomes a card, some also move the map
export type ProjectRow = {
  id: string; name: string; kv: number | null; type: string | null; status: string | null; state: string | null; county: string | null;
  start: string; end: string; in_service: string; cost_usd: number | null; miles: number | null; center?: [number, number] | null;
};
export type Projects = { title: string; filters: Record<string, unknown>; rows: ProjectRow[] };
export type TimelineRow = ProjectRow & { org: string; org_short: string; mine: boolean };
export type Timeline = { title: string; years: [number, number]; rows: TimelineRow[] };
export type ForecastDay = {
  date: string; dow: string; gust_mph: number | null; wind_mph: number | null; thunder_pct: number | null; rain_in: number | null; ice_in: number | null; snow_in: number | null;
  heat_index_f: number | null; high_f: number | null; low_f: number | null; notes: string[]; quiet: boolean;
};
export type Forecast = { site: string; point: [number, number]; near: string; days: ForecastDay[]; fetched_at: string; source: string; sources: { title: string; url: string }[] };
export type Route = {
  from: string; to: string; straight_km: number; straight_mi: number; road_km: number | null; road_mi: number | null; drive_min: number | null; note: string | null; source: string;
  geometry: GeoJSON.LineString; a: [number, number]; b: [number, number];
};
export type Download = { id: number; kind: string; format: string; filename: string; size: number; filters: Record<string, unknown> };
export type Share = { id: number; token: string; path: string; kind: string; ref_id: string; title: string; expires_at: string; days: number };
export type Result = { low?: number; high?: number; value?: number | string; verdict?: string; unit?: string };
export type Explain = {
  title: string; formula: string; what: string; opportunity_id?: number; inputs: { label: string; value: string | number; unit?: string; source?: string }[];
  steps: string[]; sources: { title: string; url: string }[]; result?: Result;
  assumptions?: { key: string; label: string; low?: number; high?: number; value?: number | string; unit?: string; verified?: boolean; source?: string; page?: string; note?: string }[];
};
export type MapView = {
  tab: "overlaps" | "hazards" | "news"; period?: "now7" | "weeks" | "season" | "month"; month?: number; hazards?: string[]; ids?: number[]; filters?: Record<string, unknown>;
  partner?: string; fit?: { bbox: [number, number, number, number] } | { to: string }; layers?: { others?: boolean };
};

export type MapCard =
  | { type: "projects"; projects: Projects } | { type: "timeline"; timeline: Timeline } | { type: "forecast"; forecast: Forecast } | { type: "route"; route: Route }
  | { type: "download"; download: Download } | { type: "share"; share: Share } | { type: "explain"; explain: Explain };

export type HazardControl = { period?: MapView["period"]; month?: number; hazards?: string[]; at: number };

export const kb = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n >= 1e3 ? `${Math.round(n / 1e3)} KB` : `${n} B`);
