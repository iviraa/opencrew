export type OutlookProduct = "spc" | "spc48" | "wpc_ero" | "nhc_gtwo" | "nhc_wsp";

export type OutlookProps = {
  id: number; product: OutlookProduct; day: number | null; issued: string; valid_from: string; valid_to: string;
  level: string; rank: number; label: string; props: Record<string, string>;
};

export type HeadsUp = {
  id: string; kind: "severe" | "severe48" | "flood" | "tropical" | "wind" | "watch"; product: string; level: string; rank: number;
  when: string; day: string; text: string; sites: string[]; assets: Record<string, number>; bbox: [number, number, number, number] | null;
  issued: string | null;
};

export type OutlookFrame = {
  outlooks: GeoJSON.FeatureCollection<GeoJSON.Geometry, OutlookProps>; heads_up: HeadsUp[];
  view: string; known: string; clock: string; available: Record<string, { n: number; first?: string; last?: string; note?: string }>;
};

export type JobHazard = {
  job_id?: string; name: string; in_floodplain: boolean | null; flood_zones: string[]; hurricanes_50mi: number; storms_50mi: number;
  peak_month: number | null; since_year: number; hurricane_exposure: boolean; lines: string[];
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const outlookApi = {
  frame: (at: number | null, scenario: "none" | "helene") =>
    call<OutlookFrame>(`/outlook/frame?scenario=${scenario}${at == null ? "" : `&at=${new Date(at).toISOString()}`}`),
  refresh: () => call<Record<string, unknown>>("/outlook/refresh", { method: "POST" }),
  hazards: () => call<Record<string, JobHazard>>("/hazards"),
  hazard: (jobId: string) => call<JobHazard>(`/hazards/${encodeURIComponent(jobId)}`),
};

// one color ramp for every product: rank 1 low to 5 high
export const RISK_COLOR = ["#ffd166", "#ffb020", "#ff7a3d", "#ff4f5e", "#c9184a"];
export const riskColor = (rank: number) => RISK_COLOR[Math.min(Math.max(rank, 1), 5) - 1];

export const PRODUCT_LABEL: Record<string, string> = {
  spc: "Severe storms (SPC)", spc48: "Severe storms, days 4 to 8 (SPC)", wpc_ero: "Flash flooding (WPC)",
  nhc_gtwo: "Tropical development (NHC)", nhc_wsp: "Tropical storm winds (NHC)",
};
