export type Tier = "crossing" | "land" | "site" | "crew";

export type Job = {
  id: string; org_id: string; org_name: string; color: string; name: string; ref: string; description: string | null;
  job_type: string; phase: string | null; parent_job_id: string | null; voltage_kv: number | null; endpoints: string[]; geom_quality: string; start_at: string; end_at: string;
  window_basis: string; in_service: string; cost_usd: number | null; confidence: number; simulated: boolean;
  source_title: string; source_page: number;
};

export type Opportunity = {
  id: number; job_a: string; job_b: string; distance_m: number; center_distance_m: number; overlap_m: number; tier: Tier;
  time_overlap: number; time_gap_days: number | null; score: number; flags: string[]; savings_low: number; savings_high: number;
  status: string; link: GeoJSON.LineString;
  a_name: string; a_phase: string | null; a_org: string; a_color: string; a_conf: number; a_quality: string;
  b_name: string; b_phase: string | null; b_org: string; b_color: string; b_conf: number; b_quality: string;
};

export type Savings = { low: number; high: number; items: Record<string, { low: number; high: number }> };

export type OpportunityDetail = Opportunity & { a: Job; b: Job; shareable: string[]; savings: Savings };

export type Assumption = { low: number; high: number; unit: string; label: string; source: string; verified: boolean };

export type JobCollection = GeoJSON.FeatureCollection<GeoJSON.Geometry, Job>;

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  jobs: (horizon = "long") => call<JobCollection>(`/jobs?horizon=${horizon}`),
  opportunities: (horizon = "long") => call<Opportunity[]>(`/opportunities?horizon=${horizon}`),
  opportunity: (id: number) => call<OpportunityDetail>(`/opportunities/${id}`),
  assumptions: () => call<Record<string, Assumption>>("/assumptions"),
  savings: (id: number, assumptions: Record<string, { low: number; high: number }>) =>
    call<Savings>(`/opportunities/${id}/savings`, { method: "POST", body: JSON.stringify({ assumptions }) }),
  setStatus: (id: number, status: string) =>
    call<{ id: number; status: string }>(`/opportunities/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
};
