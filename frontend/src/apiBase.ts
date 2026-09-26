// settings baked in at build time (VITE_*) or handed over by the server at runtime (/config.js), so one image runs anywhere
type Cfg = { supabaseUrl?: string; supabaseKey?: string; apiUrl?: string };
const cfg: Cfg = (window as unknown as { __CREWLY__?: Cfg }).__CREWLY__ ?? {};
export const API_BASE = (import.meta.env.VITE_API_URL || cfg.apiUrl || "").replace(/\/$/, "");
export const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || cfg.supabaseUrl || "";
export const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || cfg.supabaseKey || "";
