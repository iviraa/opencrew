import { API_BASE } from "./apiBase";
export type Tier = "crossing" | "land" | "site" | "crew";

export type Job = {
  id: string; org_id: string; org_name: string; color: string; name: string; ref: string; description: string | null;
  job_type: string; phase: string | null; parent_job_id: string | null; voltage_kv: number | null; endpoints: string[]; geom_quality: string; start_at: string; end_at: string;
  window_basis: string; in_service: string; cost_usd: number | null; confidence: number; simulated: boolean;
  source_title: string; source_page: number; history: { observed_at: string; start_at: string; end_at: string }[] | null;
};

export type Opportunity = {
  id: number; job_a: string; job_b: string; horizon: string; distance_m: number; center_distance_m: number; overlap_m: number; drive_min: number | null; drive_km: number | null; meet_lon: number | null; meet_lat: number | null; meet_road: string | null; meet_min: number | null; tier: Tier;
  time_overlap: number; time_gap_days: number | null; risk: number; vulnerability: number; score: number; flags: string[]; savings_low: number; savings_high: number;
  status: string; link: GeoJSON.LineString;
  a_name: string; a_phase: string | null; a_start: string; a_org: string; a_color: string; a_conf: number; a_quality: string;
  b_name: string; b_phase: string | null; b_start: string; b_org: string; b_color: string; b_conf: number; b_quality: string;
};

export type SavingsFactors = { same_time: number; drive: number; size: number | null; kv: number | null; gap_days: number | null };
export type Savings = { low: number; high: number; items: Record<string, { low: number; high: number }>; factors?: SavingsFactors };

export type OpportunityDetail = Opportunity & { a: Job; b: Job; shareable: string[]; savings: Savings };

export type Assumption = { low: number; high: number; unit: string; label: string; source: string; verified: boolean };

export type CrewlyAction =
  | { type: "filter"; horizon: string; tier: Tier | null; opportunity_ids: number[] }
  | { type: "select"; horizon: string | null; opportunity_id: number }
  | { type: "storm"; at: string }
  | { type: "live" }
  | { type: "reload" }
  | { type: "outlook"; at: string; scenario: "none" | "helene" }
  | { type: "status"; opportunity_id: number; status: string }
  | { type: "assumptions"; values: Record<string, { low: number; high: number }> }
  | { type: "view"; horizon: string | null; tier: Tier | null; tab: string | null }
  | { type: "timeline"; years: [number, number] | null; orgs: string[] | null }
  | { type: "brief"; opportunity_id: number; markdown: string; source: string }
  | { type: "plan" }
  | { type: "pending_constraints"; constraints: PlanConstraints; rules: string[] }
  | { type: "fly"; bbox: [number, number, number, number] };

export type CrewlyReply = { reply: string; ui_actions: CrewlyAction[]; tool_calls: { name: string; args: Record<string, unknown> }[]; unsourced: string[] };

export type Contact = { id: number; org_id: string; org_name: string; role: string; email: string | null; is_demo: boolean };

export type OutreachItem = {
  id: number; opportunity_id: number; contact_id: number; subject: string; body: string; state: string; approved_by: string | null;
  sent_at: string | null; reply_summary: string | null; email: string | null; org_name: string;
};

export type NewsArticle = { title: string; source: string; url: string; quote: string; published: string | null; topic: NewsTopic; copies: number };
export type NewsTopic = "damage" | "outage" | "work" | "other";
export type NewsPin = { ts: string; topic: NewsTopic; count: number; articles: NewsArticle[]; near_name: string; near_mi: number; verified: boolean };
export type WindRisk = { job_id: string; site: string; day: string; gust_mph: number; work: string; alert: string };

export type StormFrame = {
  at: string; landfall: string; window: [string, string];
  cone: GeoJSON.FeatureCollection; track: GeoJSON.FeatureCollection; warnings: GeoJSON.FeatureCollection;
  reports: GeoJSON.FeatureCollection; staging: GeoJSON.FeatureCollection; exposure: Record<string, number>;
  incidents: GeoJSON.FeatureCollection; mode?: string;
};

export type LiveFrame = StormFrame & {
  scenario: "none" | "helene"; range: [string, string]; is_live: boolean; storm_active: boolean;
  news: GeoJSON.FeatureCollection<GeoJSON.Point, NewsPin>; active_phases: GeoJSON.FeatureCollection; active_labels: GeoJSON.FeatureCollection;
  wind_risks: WindRisk[];
};

export type IncidentSource = { type: string; name: string; url?: string; title?: string; quote_evidence?: string; method?: string };

export type IncidentDetail = {
  id: number; ts: string; mode: string; kind: string; where_text: string; precision: string; utility_mentioned: string | null;
  customers_affected: number | null; confidence: number; verified: boolean; needs_confirmation: boolean; lat: number; lon: number;
  sources: IncidentSource[]; nearest: Record<string, { asset: string; km: number }> | null;
};

export type PhaseRisk = { job_id: string; site: string; day: string; gust_mph: number; work: string; alert: string; fetched_at: string };

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

export type BurstSpec = {
  label: string; resource: string; phase: string; window: [number, number]; weeks: number; mob_low_k: number; mob_high_k: number;
  applies: string[]; enabled: boolean;
};

export type PlanConstraints = {
  max_slip_months: number; slip_overrides: Record<string, number>; max_advance_months: number;
  crew_counts: Record<string, Record<string, number>>; blackouts: { site: string; months: number[]; phase_kind: string }[];
  chain_gap_months: number; crew_drive_min: number; crew_km: number; yard_km: number; costs: Record<string, number>;
  bursts: Record<string, BurstSpec>; burst_gap_weeks: number; joint_contracting: boolean; jc_overlap_months: number; model?: number;
};

export type PlanMetrics = {
  projects: number; mobilizations: number; specialty_mobilizations: number; specialty: Record<string, number>; all_mobilizations: number;
  shared_bursts: number; contractor_pairs: number; yards: number; idle_months: number; burst_idle_weeks: number; burst_shift_weeks: number;
  slip_months: number; slipped_projects: number; late_projects: number; advance_months: number; cost_k: number;
};

export type PlanBurst = { burst: string; label: string; resource: string; shared: boolean; start: string; end: string; partner: string | null };

export type PlanRow = {
  job_id: string; name: string; org: string; crew: string; crew_org: string; yard: string; yard_label: string;
  phases: { phase: string; start: string; end: string }[]; filed_start: string; filed_end: string; in_service: string;
  slip: number; slip_limit: number; shift: number; baseline_crew: string | null; why: string | null; bursts: PlanBurst[];
};

export type PlanDecisionItem = {
  opportunity_id: number; a: string; b: string; job_a: string; job_b: string; decision: "share" | "no_share"; sentence: string;
  reasons: { rule: string }[]; drive_min: number | null; km: number | null; eligible: boolean; shared: string[]; contractor?: boolean;
};

export type Headline = {
  mobilizations_before: number; mobilizations_after: number; mobilizations_cut: number; mobilizations_cut_pct: number;
  crew_mobilizations_before: number; crew_mobilizations_after: number; specialty: Record<string, { label: string; before: number; after: number }>;
  shared_bursts: number; yards_before: number; yards_after: number; savings_low: number; savings_high: number; late_projects: number; cost_cut_k: number;
};

export type PlanHeadline = Headline & {
  crews: Record<string, Record<string, number>>; free_projects?: number;
  solver?: { separate: string; coordinated: string; coordinated_gap_k: number; separate_gap_k?: number };
  joint_contracting: (Headline & { contractor_pairs: number; pairs: string[][]; assumption: string }) | null;
};

export type JointPlan = {
  plan_id: number; status: string; problem?: string | null; constraints: PlanConstraints; baseline: PlanMetrics | null;
  coordinated: PlanMetrics | null; headline: PlanHeadline | null; schedule: PlanRow[]; decisions: PlanDecisionItem[];
};

export type PlanCheck = { constraints: PlanConstraints; notes: string[]; errors: string[]; valid: boolean };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const json = typeof init?.body === "string";  // FormData sets its own multipart header
  const res = await fetch(`${API_BASE}/api${path}`, { ...init, headers: json ? { "Content-Type": "application/json" } : undefined });
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
  liveFrame: (at: number | null, scenario: "none" | "helene") =>
    call<LiveFrame>(`/live/frame?scenario=${scenario}${at == null ? "" : `&at=${new Date(at).toISOString()}`}`),
  storm: (at: number | null, mode = "replay") =>
    call<StormFrame>(`/storm/frame?mode=${mode}${at == null ? "" : `&at=${new Date(at).toISOString()}`}`),
  incident: (id: number) => call<IncidentDetail>(`/incidents/${id}`),
  phaseRisks: () => call<PhaseRisk[]>("/weather/phase_risks"),
  livePoll: () => call<Record<string, unknown>>("/live/poll", { method: "POST" }),
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
  plan: () => call<JointPlan>("/plan"),
  solvePlan: (constraints: Partial<PlanConstraints>) => call<JointPlan>("/plan/solve", { method: "POST", body: JSON.stringify({ constraints }) }),
  checkPlan: (constraints: Partial<PlanConstraints>) => call<PlanCheck>("/plan/constraints", { method: "POST", body: JSON.stringify({ constraints }) }),
  explainPlan: (id: number) => call<{ decisions: PlanDecisionItem[] }>(`/plan/explain?opportunity_id=${id}`),
};
