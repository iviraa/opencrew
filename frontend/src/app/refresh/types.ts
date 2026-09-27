// a planner list refresh as the chat shows it: one row per source, with the diff a new edition would apply
export type RefreshSample = { id: string; name: string; org_id: string; changes?: Record<string, [unknown, unknown]> };
export type RefreshDiff = {
  added: number; changed: number; removed: number; old_count: number; new_count: number; review?: number | null;
  samples?: { added: RefreshSample[]; removed: RefreshSample[]; changed: RefreshSample[] }; overlaps?: unknown;
};
export type RefreshRow = {
  id: number | null; source: string; planner: string; name: string; status: "never" | "unchanged" | "rejected" | "staged" | "promoted" | "failed";
  edition: string | null; url: string | null; found_via: string | null; checked_at: string | null; promoted_at: string | null;
  validation: string | null; error: string | null; summary: string | null; needs_review: boolean; diff: RefreshDiff | null; cadence_days: number; running: boolean;
};
export type RefreshCardData = { rows: RefreshRow[]; ask?: boolean };
