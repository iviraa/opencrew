export type Tier = "crossing" | "land" | "site" | "crew";

export type Job = {
  id: string; org_id: string; org_name: string; color: string; name: string; ref: string; description: string | null;
  job_type: string; phase: string | null; parent_job_id: string | null; voltage_kv: number | null; endpoints: string[]; geom_quality: string; start_at: string; end_at: string;
  window_basis: string; in_service: string; cost_usd: number | null; confidence: number; simulated: boolean;
  source_title: string; source_page: number; history: { observed_at: string; start_at: string; end_at: string }[] | null;
};

export type Opportunity = {
  id: number; job_a: string; job_b: string; distance_m: number; center_distance_m: number; overlap_m: number; drive_min: number | null; drive_km: number | null; tier: Tier;
  time_overlap: number; time_gap_days: number | null; risk: number; vulnerability: number; score: number; flags: string[]; savings_low: number; savings_high: number;
  status: string; link: GeoJSON.LineString;
  a_name: string; a_phase: string | null; a_start: string; a_org: string; a_color: string; a_conf: number; a_quality: string;
  b_name: string; b_phase: string | null; b_start: string; b_org: string; b_color: string; b_conf: number; b_quality: string;
};

export type Savings = { low: number; high: number; items: Record<string, { low: number; high: number }> };

export type OpportunityDetail = Opportunity & { a: Job; b: Job; shareable: string[]; savings: Savings };

export type Assumption = { low: number; high: number; unit: string; label: string; source: string; verified: boolean };

export type CrewlyAction =
  | { type: "filter"; horizon: string; tier: Tier | null; opportunity_ids: number[] }
  | { type: "select"; horizon: string | null; opportunity_id: number }
  | { type: "storm"; at: string }
  | { type: "reload" }
  | { type: "status"; opportunity_id: number; status: string }
  | { type: "assumptions"; values: Record<string, { low: number; high: number }> }
  | { type: "view"; horizon: string | null; tier: Tier | null; tab: string | null }
  | { type: "timeline"; years: [number, number] | null; orgs: string[] | null }
  | { type: "brief"; opportunity_id: number; markdown: string; source: string }
  | { type: "plan" }
  | { type: "fly"; bbox: [number, number, number, number] };

export type CrewlyReply = { reply: string; ui_actions: CrewlyAction[]; tool_calls: { name: string; args: Record<string, unknown> }[]; unsourced: string[] };

export type Contact = { id: number; org_id: string; org_name: string; role: string; email: string | null; is_demo: boolean };

export type OutreachItem = {
  id: number; opportunity_id: number; contact_id: number; subject: string; body: string; state: string; approved_by: string | null;
  sent_at: string | null; reply_summary: string | null; email: string | null; org_name: string;
};

export type StormFrame = {
  at: string; landfall: string; window: [string, string];
  cone: GeoJSON.FeatureCollection; track: GeoJSON.FeatureCollection; warnings: GeoJSON.FeatureCollection;
  reports: GeoJSON.FeatureCollection; staging: GeoJSON.FeatureCollection; exposure: Record<string, number>;
};

export type ReviewItem = { id: number; org_id: string; reason: string; source_page: number; name: string; in_service: string; endpoints: string[] | null };

export type ProcurementItem = { id: string; name: string; in_service: string; placed: boolean };

export type ProcurementGroup = {
  voltage_kv: number; kind: string; desc: ProcurementItem; gpc: (ProcurementItem & { year_gap: number; reason: string })[];
};

export type IngestResult = {
  org: string; method: string; pages: number; rows: number; placed?: number; unplaced?: number; ceii_page?: number; invalid?: number;
  long: { pairs: number }; near: { pairs: number }; seconds: number;
};

export type Vendor = { name: string; address: string; phone: string | null; website: string | null; rating: number | null; distance_km: number };

export type JobCollection = GeoJSON.FeatureCollection<GeoJSON.Geometry, Job>;

export type PlanLimits = { max_delay_months: number; max_drive_min: number; min_overlap_months: number };

export type PlanDecisionItem = {
  opportunity_id: number; a: string; b: string; decision: "share" | "no_share"; sentence: string; savings_mid: number;
  drive_min: number | null; shift: { project: string; months: number } | null; overlap_months: number | null; reasons: { rule: string }[];
};

export type CrewPlanResult = {
  plan_id: number; limits: PlanLimits; decisions: PlanDecisionItem[];
  summary: { pairs: number; shared: number; savings_mid_total: number; rejected_by: Record<string, number> };
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const json = typeof init?.body === "string";  // FormData sets its own multipart header
  const res = await fetch(`/api${path}`, { ...init, headers: json ? { "Content-Type": "application/json" } : undefined });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text error */ }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  jobs: (horizon = "long") => call<JobCollection>(`/jobs?horizon=${horizon}`),
  opportunities: (horizon = "long") => call<Opportunity[]>(`/opportunities?horizon=${horizon}`),
  opportunity: (id: number) => call<OpportunityDetail>(`/opportunities/${id}`),
  assumptions: () => call<Record<string, Assumption>>("/assumptions"),
  savings: (id: number, assumptions: Record<string, { low: number; high: number }>) =>
    call<Savings>(`/opportunities/${id}/savings`, { method: "POST", body: JSON.stringify({ assumptions }) }),
  brief: (id: number) => call<{ markdown: string; summary_source: string }>(`/opportunities/${id}/brief`, { method: "POST" }),
  tracts: () => call<GeoJSON.FeatureCollection>("/layers/tracts"),
  grid: () => call<GeoJSON.FeatureCollection>("/layers/grid"),
  storm: (at: number) => call<StormFrame>(`/storm/frame?at=${new Date(at).toISOString()}`),
  ingest: (form: FormData) => call<IngestResult>("/ingest", { method: "POST", body: form }),
  vendors: (id: number, service: string) =>
    call<{ vendors: Vendor[] }>(`/vendors?opportunity_id=${id}&service=${encodeURIComponent(service)}`),
  driveZone: (id: number) => call<GeoJSON.Feature>(`/drive/zone?opportunity_id=${id}`),
  procurement: () => call<ProcurementGroup[]>("/procurement"),
  review: () => call<ReviewItem[]>("/review"),
  place: (id: number, lon: number, lat: number) => call<unknown>(`/review/${id}/place`, { method: "POST", body: JSON.stringify({ lon, lat }) }),
  contacts: (id: number) => call<Contact[]>(`/opportunities/${id}/contacts`),
  outreach: (id: number) => call<OutreachItem[]>(`/opportunities/${id}/outreach`),
  draftOutreach: (opportunity_id: number, contact_id: number) =>
    call<OutreachItem>("/outreach", { method: "POST", body: JSON.stringify({ opportunity_id, contact_id }) }),
  editOutreach: (id: number, subject: string, body: string) =>
    call<OutreachItem>(`/outreach/${id}`, { method: "PATCH", body: JSON.stringify({ subject, body }) }),
  approveOutreach: (id: number, approved_by: string) =>
    call<OutreachItem>(`/outreach/${id}/approve`, { method: "POST", body: JSON.stringify({ approved_by }) }),
  sendOutreach: (id: number) => call<OutreachItem>(`/outreach/${id}/send`, { method: "POST" }),
  markReplied: (id: number) => call<OutreachItem>(`/outreach/${id}/replied`, { method: "POST", body: JSON.stringify({ summary: "" }) }),
  crewly: (messages: { role: string; text: string }[]) => call<CrewlyReply>("/crewly", { method: "POST", body: JSON.stringify({ messages }) }),
  setStatus: (id: number, status: string) =>
    call<{ id: number; status: string }>(`/opportunities/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
  plan: () => call<CrewPlanResult>("/plan"),
  runPlan: (limits: PlanLimits) => call<CrewPlanResult>("/plan/run", { method: "POST", body: JSON.stringify(limits) }),
  explainPlan: (id: number) => call<{ decisions: PlanDecisionItem[] }>(`/plan/explain?opportunity_id=${id}`),
};
