import { API_BASE } from "./apiBase";
export type Scenario = "helene" | "none";

export type LikelyHit = {
  org: string; name: string; in_cone: number; tropical_storm_winds: number; damaging_winds: number; hurricane_winds: number;
  counties: { county: string; substations: number }[]; sentence: string;
};

export type PauseSite = {
  job_id: string; project: string; org: string; phase: string; lon: number; lat: number; arrival: string; pause_by: string;
  hours_left: number; status: "stop now" | "pause soon" | "watch"; sentence: string;
};

export type StagingYard = {
  lon: number; lat: number; county: string; shared: boolean; sentence: string;
  serves: { org: string; name: string; substations: number; minutes: number | null; county: string }[];
};

export type Assumption = { value: number | string; label: string };

export type Briefing = {
  storm: null | {
    name: string; advisory: string; issued: string; at: string; first_winds: string | null; hours_to_first_winds: number | null; radii_source: string;
    cone: GeoJSON.Geometry; wind_zone: GeoJSON.Geometry | null; damage_zone: GeoJSON.Geometry | null; hurricane_zone: GeoJSON.Geometry | null;
  };
  reason?: string;
  headline?: string;
  likely_hit?: LikelyHit[];
  pause?: PauseSite[];
  staging?: StagingYard[];
  crews?: { org: string; name: string; substations: number; crews: number; sentence: string }[];
  assumptions?: Record<string, Assumption>;
};

export type PlanSummary = { done_hours: number; avg_wait_hours: number; weighted_wait_hours: number; status: string };

export type CrewRoute = {
  crew: string; org: string; yard: { lon: number; lat: number; county: string };
  jobs: { job_id: string; name: string; org: string; lon: number; lat: number; start: string; end: string; drive_min: number; cross_utility: boolean }[];
};

export type RestorationPlan = {
  jobs: number; headline: string; mutual_aid?: boolean; at_first_report?: string;
  crews?: Record<string, number>;
  summary?: { alone: PlanSummary; mutual_aid: PlanSummary; cross_utility_jobs: number };
  routes?: CrewRoute[];
  explanations?: { job_id: string; crew: string; crew_id: string; cross_utility: boolean; sentence: string }[];
  assumptions?: Record<string, Assumption>;
};

async function get<T>(path: string, params: Record<string, string | number | boolean | undefined>): Promise<T> {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]));
  const res = await fetch(`${API_BASE}/api${path}?${q}`);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text error */ }
    throw new Error(detail);
  }
  return res.json();
}

export const stormApi = {
  briefing: (at: string, scenario: Scenario, opts: { safety_margin_h?: number; crews_per_substation?: number } = {}) =>
    get<Briefing>("/storm/briefing", { at, scenario, ...opts }),
  restoration: (at: string, scenario: Scenario, mutual_aid = true, opts: { crews_gpc?: number; crews_desc?: number; repair_h?: number; max_drive_min?: number } = {}) =>
    get<RestorationPlan>("/storm/restoration_plan", { at, scenario, mutual_aid, ...opts }),
};
