import { Check, ChevronDown, ChevronUp, Loader2, RefreshCw, ShieldAlert, Upload } from "lucide-react";
import { useState } from "react";
import { api } from "../data";
import { say } from "../mascot";
import type { RefreshCardData, RefreshRow } from "./types";

const TONE: Record<RefreshRow["status"], string> = {
  never: "bg-soft text-muted", unchanged: "bg-soft text-muted", staged: "bg-grape-soft text-grape", promoted: "bg-save-soft text-save",
  rejected: "bg-warn-soft text-warn", failed: "bg-warn-soft text-warn",
};
const LABEL: Record<RefreshRow["status"], string> = {
  never: "not checked yet", unchanged: "up to date", staged: "new edition waiting", promoted: "applied", rejected: "refused: layout drifted", failed: "check failed",
};
const ago = (iso: string | null) => {
  if (!iso) return "";
  const h = (Date.now() - new Date(iso).getTime()) / 36e5;
  return h < 1 ? "just now" : h < 24 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`;
};
const val = (v: unknown) => (v == null || v === "" ? "blank" : String(v));

// one planner's refresh: its status, the diff a new edition brings, and the only two actions: check again, or apply what is staged
function Row({ row: initial, ask }: { row: RefreshRow; ask?: boolean }) {
  const [row, setRow] = useState(initial);
  const [open, setOpen] = useState(!!ask);
  const [busy, setBusy] = useState<"check" | "apply" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const d = row.diff;

  const check = async () => {
    setBusy("check"); setErr(null);
    try {
      await api.send(`/api/app/refresh/check/${row.source}`, "POST", {});
      setRow({ ...row, running: true }); say(`Checking ${row.planner}'s site. Ask me what changed in a minute or two.`, "thinking");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const apply = async () => {
    if (row.id == null) return;
    setBusy("apply"); setErr(null);
    try {
      const r = await api.send<RefreshRow>(`/api/app/refresh/${row.id}/promote`, "POST", {});
      setRow(r); say(`${row.planner} is live: ${r.summary ?? "applied"}.`, "happy");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); say("That edition would not apply cleanly, nothing changed.", "sad"); }
    finally { setBusy(null); }
  };

  return (
    <div className="rounded-xl border-2 border-line bg-white">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-sm font-semibold">{row.planner}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${TONE[row.status]}`}>{row.running ? "checking now" : LABEL[row.status]}</span>
            {row.needs_review && row.status === "staged" && <span className="flex items-center gap-1 text-[11px] font-semibold text-warn"><ShieldAlert size={12} /> big change, needs a look</span>}
          </div>
          <div className="truncate text-[11px] text-faint">
            {row.edition ? `edition ${row.edition}` : row.name}{row.checked_at ? ` · checked ${ago(row.checked_at)}` : ""}{row.found_via === "discovery_failed" ? " · index page unreadable, used the known link" : ""}
          </div>
        </div>
        {d && <button type="button" onClick={() => setOpen(!open)} aria-label={open ? "Hide the diff" : "Show the diff"} className="rounded-full p-1 hover:bg-soft">{open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}</button>}
      </div>
      {row.summary && <div className="px-2.5 pb-1 text-xs">{row.summary}</div>}
      {(row.error || row.validation) && row.status !== "promoted" && row.status !== "staged" && (
        <div className="px-2.5 pb-2 text-xs text-warn">{row.error ?? row.validation}{row.status === "rejected" ? ". The data on the map is unchanged." : ""}</div>
      )}
      {open && d?.samples && (
        <div className="mx-2.5 mb-2 flex flex-col gap-1 rounded-lg bg-soft p-2 text-[11px]">
          {d.samples.changed.slice(0, 5).map((s) => (
            <div key={s.id}><span className="font-semibold">{s.name}</span>: {Object.entries(s.changes ?? {}).map(([f, [a, b]]) => `${f} ${val(a)} → ${val(b)}`).join("; ")}</div>
          ))}
          {d.samples.added.slice(0, 3).map((s) => <div key={s.id}><span className="font-semibold text-save">new</span> {s.name}</div>)}
          {d.samples.removed.slice(0, 3).map((s) => <div key={s.id}><span className="font-semibold text-warn">gone</span> {s.name}</div>)}
          {d.review != null && d.review > 0 && <div className="text-faint">{d.review} rows could not be placed and would go to review</div>}
        </div>
      )}
      {err && <div className="px-2.5 pb-2 text-xs text-warn">{err}</div>}
      <div className="flex gap-1.5 px-2.5 pb-2">
        <button type="button" onClick={check} disabled={busy != null || row.running} className="flex items-center gap-1 rounded-full border-2 border-line px-2.5 py-1 text-xs font-semibold hover:border-ink disabled:opacity-50">
          {busy === "check" || row.running ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Check again
        </button>
        {row.status === "staged" && row.id != null && (
          <button type="button" onClick={apply} disabled={busy != null} className="flex items-center gap-1 rounded-full bg-grape px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-50">
            {busy === "apply" ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} Apply update
          </button>
        )}
        {row.status === "promoted" && <span className="flex items-center gap-1 text-xs text-save"><Check size={13} /> live{row.promoted_at ? ` ${ago(row.promoted_at)}` : ""}</span>}
      </div>
    </div>
  );
}

export default function RefreshCard({ card }: { card: RefreshCardData }) {
  return (
    <div className="pop-in flex flex-col gap-1.5 rounded-2xl border-2 border-pen bg-white p-2">
      <div className="px-1 text-xs font-semibold text-faint">Planner lists {card.ask ? "· apply only when you are sure" : ""}</div>
      {card.rows.map((r) => <Row key={`${r.source}-${r.id ?? "x"}`} row={r} ask={card.ask} />)}
    </div>
  );
}
