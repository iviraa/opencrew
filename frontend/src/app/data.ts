import { createClient, type Session } from "@supabase/supabase-js";
import type { Job, Opportunity, OpportunityDetail } from "../api";

export const supabase = createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY);

export const EMAIL_DOMAIN = "crewly.test";  // people log in with a username; auth wants an email

export type CompanyId = "desc" | "gpc";
export const COMPANY: Record<CompanyId, { name: string; short: string; color: string; soft: string }> = {
  desc: { name: "Dominion Energy SC", short: "Dominion", color: "#2f6bff", soft: "#e5edff" },
  gpc: { name: "Georgia Power", short: "Georgia Power", color: "#ff5d5d", soft: "#ffe8e8" },
};

export type Me = { company: CompanyId; name: string; other: CompanyId; other_name: string; username: string };

export type Overlap = Opportunity & { a_end: string; b_end: string };
export type OverlapDetail = OpportunityDetail & { a_end: string; b_end: string };
export type Jobs = GeoJSON.FeatureCollection<GeoJSON.Geometry, Job>;

export type RequestSummary = { title: string; ours: string; theirs: string; tier: string; savings_low: number; savings_high: number };

export type CollabRequest = {
  id: number; opportunity_id: number; from_company: CompanyId; to_company: CompanyId; summary: RequestSummary;
  note: string | null; status: "pending" | "approved" | "declined"; feedback: string | null;
  created_at: string; responded_at: string | null;
};

export type Notice = { id: number; company_id: CompanyId; request_id: number; kind: "request" | "approved" | "declined"; created_at: string; read_at: string | null };

export type ChatAction = {  // what the chat asks the screen to do
  type: string; ids?: number[]; id?: number; opportunity_id?: number; opportunity_ids?: number[]; bbox?: [number, number, number, number];
};

export type ChatReply = { reply: string; ui_actions: ChatAction[]; unsourced: string[]; offline?: boolean };

let session: Session | null = null;
supabase.auth.getSession().then(({ data }) => { session = data.session; });
supabase.auth.onAuthStateChange((_e, s) => { session = s; });

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const token = session?.access_token ?? (await supabase.auth.getSession()).data.session?.access_token;
  const res = await fetch(path, { ...init, headers: { ...init?.headers, Authorization: `Bearer ${token}`, "Content-Type": "application/json" } });
  if (res.status === 401) await supabase.auth.signOut();  // stale login: back to the login page
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText);
  return res.json();
}

export const api = {
  me: () => call<Me>("/api/app/me"),
  projects: () => call<Jobs>("/api/app/projects"),
  overlaps: () => call<{ overlaps: Overlap[]; jobs: Jobs }>("/api/app/overlaps"),
  overlap: (id: number) => call<OverlapDetail>(`/api/opportunities/${id}`),
  chat: (messages: { role: "user" | "model"; text: string }[]) =>
    call<ChatReply>("/api/app/chat", { method: "POST", body: JSON.stringify({ messages }) }),
};

// weather and news reuse the planner's public endpoints
export const publicApi = {
  get: async <T,>(path: string) => {
    const res = await fetch(path);
    if (!res.ok) throw new Error(res.statusText);
    return res.json() as Promise<T>;
  },
};

export const requests = {
  list: async () => {
    const { data, error } = await supabase.from("collab_request").select("*").order("created_at", { ascending: false });
    if (error) throw error;
    return data as CollabRequest[];
  },
  send: async (me: Me, op: Overlap | OverlapDetail, note: string) => {
    const mineA = op.a_org === me.company;
    const summary: RequestSummary = {
      title: `${mineA ? op.a_name : op.b_name} × ${mineA ? op.b_name : op.a_name}`, ours: mineA ? op.a_name : op.b_name,
      theirs: mineA ? op.b_name : op.a_name, tier: op.tier, savings_low: op.savings_low, savings_high: op.savings_high,
    };
    const { data: user } = await supabase.auth.getUser();
    const { data, error } = await supabase.from("collab_request").insert({
      opportunity_id: op.id, from_company: me.company, to_company: me.other, summary, note: note.trim() || null, created_by: user.user?.id,
    }).select().single();
    if (error) throw error;
    return data as CollabRequest;
  },
  respond: async (id: number, decision: "approved" | "declined", feedback: string) => {
    const { data, error } = await supabase.rpc("respond_request", { request_id: id, decision, feedback: feedback.trim() || null });
    if (error) throw error;
    return data as CollabRequest;
  },
};

export const notices = {
  list: async () => {
    const { data, error } = await supabase.from("notification").select("*").order("created_at", { ascending: false }).limit(50);
    if (error) throw error;
    return data as Notice[];
  },
  markRead: async (ids: number[]) => {
    if (!ids.length) return;
    await supabase.from("notification").update({ read_at: new Date().toISOString() }).in("id", ids);
  },
};

export const usd = (n: number) => n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `$${Math.round(n / 1e3)}k` : `$${Math.round(n)}`;
export const month = (s: string) => new Date(s).toLocaleDateString("en-US", { month: "short", year: "numeric" });
export const ago = (s: string) => {
  const m = Math.round((Date.now() - Date.parse(s)) / 60e3);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
export const miles = (m: number) => `${(m / 1609.344).toFixed(m < 16093 ? 1 : 0)} mi`;
export const TIER_LABEL: Record<string, { label: string; hint: string; color: string }> = {
  crossing: { label: "Crossing", hint: "The lines cross", color: "#7c4dff" },
  land: { label: "Same land", hint: "Under 1 mile apart", color: "#ff4fa3" },
  site: { label: "Same site", hint: "Under 5 miles apart", color: "#00b8a9" },
  crew: { label: "Crew range", hint: "Close enough to share crews", color: "#ffb020" },
};
