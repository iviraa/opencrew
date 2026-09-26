import type { ChatMsg } from "./Chat";
import { supabase } from "./data";

// chat turns and saved notes live in supabase so they follow the company across reloads and devices
const KEEP = 40;

type Row = { id: number; role: "user" | "model"; text: string; meta: Record<string, unknown> };
export type Memory = { id: number; text: string; created_at: string };

export const chatHistory = {
  load: async (): Promise<ChatMsg[]> => {
    const { data, error } = await supabase.from("chat_message").select("id,role,text,meta").order("id", { ascending: false }).limit(KEEP);  // ids keep insert order within a turn
    if (error) throw error;
    return (data as Row[]).reverse().map((r) => ({ ...r.meta, role: r.role, text: r.text }));
  },
  save: async (msgs: ChatMsg[]) => {
    if (!msgs.length) return;
    const rows = msgs.map(({ role, text, ...meta }) => ({ role, text: text.slice(0, 8000), meta }));  // everything else (cards, confirms) rides in meta
    await supabase.from("chat_message").insert(rows);
  },
  clear: async (company: string) => {
    await supabase.from("chat_message").delete().eq("company_id", company);
  },
};

export const memories = {
  list: async () => {
    const { data, error } = await supabase.from("crewly_memory").select("id,text,created_at").order("created_at");
    if (error) throw error;
    return data as Memory[];
  },
  forget: async (id: number) => {
    await supabase.from("crewly_memory").delete().eq("id", id);
  },
};
