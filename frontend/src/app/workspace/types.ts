import { supabase } from "../data";

// what the workspace tools hand the chat: one card per kind, the payload is the tool's own result
export type Note = { id: number; target_kind: string; target_id: string; text: string; when: string };
export type NotesData = { target: { kind: string; id: string; label: string | null } | null; count: number; notes: Note[] };
export type Reminder = { id: number; text: string; due: string; overdue: boolean; target_kind: string | null; target_id: string | null; done: boolean };
export type RemindersData = { count: number; reminders: Reminder[]; saved?: boolean; done?: number; delivery?: string };
export type PipelineItem = { id: number; ours: string; partner: string; savings: string };
export type PipelineData = { statuses: string[]; counts: Record<string, number>; columns: Record<string, PipelineItem[]> };
export type ProfileData = {
  company: { id: string; name: string; short: string; color: string; home_state: string | null; planner: string | null; states: string[] };
  projects: { total: number; by_kv: { kv: number | null; n: number }[]; by_type: { type: string; n: number }[]; by_status: { status: string; n: number }[] };
  overlaps_with_us: { count: number; savings_high_total: string; top: { id: number; ours: string; theirs: string; savings: string }[] };
  requests_with_us: { total: number; approved: number; declined: number; pending: number; median_response_hours: number | null };
  news: { title: string; impact: string; date: string; url: string }[]; notes: Note[]; is_us: boolean;
};
export type BriefReq = { id: number; overlap_id: number; with: string; projects: string | null; status: string; since: string };
export type BriefData = {
  week_of: string; since_last_brief: string | null; overlaps: { total: number; new: number[]; gone: number[] };
  requests: { waiting_on_us: BriefReq[]; waiting_on_them: BriefReq[]; answered_this_week: BriefReq[]; new_since_last_brief: number };
  plan: { id: number; pairs: number; proposed: number; accepted: number; savings: string } | null;
  hazards_this_week: { project: string; hazards: string[]; affected_days: Record<string, number> }[];
  news: { title: string; impact: string; date: string; url: string; overlaps: number[] }[];
  findings_starred: { id: number; title: string; kind: string }[];
};
export type HistoryEvent = { when: string; kind: string; text: string; finding_id?: number };
export type HistoryData = { opportunity_id: number; ours: string; theirs: string; partner: string; status: string; count: number; events: HistoryEvent[] };
export type ViewState = { tab?: string; partner?: string | null; focus?: number[] | null; selected?: number | null; bbox?: [number, number, number, number] | null };
export type SavedView = { id: number; name: string; state: ViewState; when: string };
export type ViewsData = SavedView[];

export type WorkspaceCard =
  | { kind: "note"; data: NotesData } | { kind: "reminder"; data: RemindersData } | { kind: "pipeline"; data: PipelineData }
  | { kind: "profile"; data: ProfileData } | { kind: "brief"; data: BriefData } | { kind: "history"; data: HistoryData }
  | { kind: "views"; data: ViewsData } | { kind: "view"; data: { name: string; state: ViewState } };

export const WORKSPACE_KINDS = new Set(["note", "reminder", "pipeline", "profile", "brief", "history", "views", "view"]);

// a tool's ui_action becomes a card: the payload sits under the action's own type name
export function cardOf(a: { type: string } & Record<string, unknown>): WorkspaceCard | null {
  if (!WORKSPACE_KINDS.has(a.type)) return null;
  const data = a.type === "view" ? { name: a.name, state: a.state } : a[a.type];
  return data ? ({ kind: a.type, data } as WorkspaceCard) : null;
}

export const STATUS_LABEL: Record<string, string> = {
  not_contacted: "Not contacted", drafted: "Drafted", sent: "Sent", replied: "Replied", call_scheduled: "Call scheduled", agreed: "Agreed", declined: "Declined",
};

// notes and views are written with the person's own login, so row security keeps them inside the company
export const notesApi = {
  all: async () => {  // every note our company wrote, newest first (RLS keeps it to us)
    const { data, error } = await supabase.from("note").select("id,target_kind,target_id,text,created_at").order("created_at", { ascending: false }).limit(500);
    if (error) throw error;
    return (data as { id: number; target_kind: string; target_id: string; text: string; created_at: string }[]).map((r) => ({ ...r, when: r.created_at.slice(0, 16).replace("T", " ") })) as Note[];
  },
  list: async (kind: string, id: string) => {
    const { data, error } = await supabase.from("note").select("id,target_kind,target_id,text,created_at").eq("target_kind", kind).eq("target_id", id).order("created_at", { ascending: false });
    if (error) throw error;
    return (data as { id: number; target_kind: string; target_id: string; text: string; created_at: string }[]).map((r) => ({ ...r, when: r.created_at.slice(0, 16).replace("T", " ") })) as Note[];
  },
  add: async (kind: string, id: string, text: string) => {
    const { data: user } = await supabase.auth.getUser();
    const { error } = await supabase.from("note").insert({ target_kind: kind, target_id: id, text: text.trim().slice(0, 2000), created_by: user.user?.id });
    if (error) throw error;
  },
  remove: async (id: number) => { await supabase.from("note").delete().eq("id", id); },
};

export const viewsApi = {
  save: async (name: string, state: ViewState) => {
    const { data: user } = await supabase.auth.getUser();
    const { error } = await supabase.from("saved_view").upsert({ name, state, created_by: user.user?.id }, { onConflict: "company_id,name" });
    if (error) throw error;
  },
};
