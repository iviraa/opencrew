import { Check, DatabaseZap, Loader2, RefreshCw, ShieldAlert, Upload } from "lucide-react";
import { useState } from "react";
import { api } from "../data";
import { say } from "../mascot";
import { Card, Chip, Drawer, Note, Pill, Row, type ChipTone } from "../ui";
import type { RefreshCardData, RefreshRow } from "./types";

const TONE: Record<RefreshRow["status"], ChipTone> = { never: "neutral", unchanged: "good", staged: "info", promoted: "good", rejected: "warn", failed: "warn" };
const LABEL: Record<RefreshRow["status"], string> = {
  never: "Not checked yet", unchanged: "Up to date", staged: "New edition waiting", promoted: "Applied", rejected: "Refused: layout drifted", failed: "Check failed",
};
const ago = (iso: string | null) => {
  if (!iso) return "";
  const h = (Date.now() - new Date(iso).getTime()) / 36e5;
  return h < 1 ? "just now" : h < 24 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} d ago`;
};
const val = (v: unknown) => (v == null || v === "" ? "blank" : String(v));

// one planner's refresh: its status, the diff a new edition brings, and the only two actions: check again, or apply what is staged
function SourceRow({ row: initial, ask }: { row: RefreshRow; ask?: boolean }) {
  const [row, setRow] = useState(initial);
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

  const counts = d ? [d.added && `${d.added} new`, d.changed && `${d.changed} changed`, d.removed && `${d.removed} gone`].filter(Boolean).join(" · ") : "";
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border-2 border-line px-2.5 py-2">
      <Row>
        <span className="text-sm font-semibold">{row.planner}</span>
        <Chip tone={row.running ? "info" : TONE[row.status]}>{row.running ? "Checking now" : LABEL[row.status]}</Chip>
        {row.needs_review && row.status === "staged" && <Chip tone="warn" icon={<ShieldAlert size={11} />}>Needs a look</Chip>}
      </Row>
      <div className="text-[11px] text-muted">
        {row.edition ? `Edition ${row.edition}` : row.name}{row.checked_at ? ` · checked ${ago(row.checked_at)}` : ""}{row.found_via === "discovery_failed" ? " · index page unreadable, used the known link" : ""}
      </div>
      {row.summary && <p className="text-xs leading-snug">{row.summary}</p>}
      {(row.error || row.validation) && row.status !== "promoted" && row.status !== "staged" && (
        <Note tone="warn">{row.error ?? row.validation}{row.status === "rejected" ? ". The data on the map is unchanged." : ""}</Note>
      )}
      {d?.samples && (
        <Drawer title="What would change" summary={counts || "no differences"} defaultOpen={!!ask}>
          {d.samples.changed.slice(0, 5).map((s) => (
            <div key={s.id} className="text-[11px]"><span className="font-semibold">{s.name}</span>: {Object.entries(s.changes ?? {}).map(([f, [a, b]]) => `${f.replace(/_/g, " ")} ${val(a)} → ${val(b)}`).join("; ")}</div>
          ))}
          {d.samples.added.slice(0, 3).map((s) => <div key={s.id} className="text-[11px]"><Chip tone="good">new</Chip> {s.name}</div>)}
          {d.samples.removed.slice(0, 3).map((s) => <div key={s.id} className="text-[11px]"><Chip tone="warn">gone</Chip> {s.name}</div>)}
          {d.review != null && d.review > 0 && <Note>{d.review} rows could not be placed and would go to review.</Note>}
        </Drawer>
      )}
      {err && <Note tone="warn">{err}</Note>}
      <Row>
        <Pill onClick={check} disabled={busy != null || row.running} icon={busy === "check" || row.running ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}>Check again</Pill>
        {row.status === "staged" && row.id != null && (
          <Pill primary onClick={apply} disabled={busy != null} icon={busy === "apply" ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}>Apply update</Pill>
        )}
        {row.status === "promoted" && <Chip tone="good" icon={<Check size={11} />}>Live{row.promoted_at ? ` ${ago(row.promoted_at)}` : ""}</Chip>}
      </Row>
    </div>
  );
}

export default function RefreshCard({ card }: { card: RefreshCardData }) {
  const staged = card.rows.filter((r) => r.status === "staged").length;
  return (
    <Card icon={<DatabaseZap size={15} />} title="Planner lists" sub={staged ? `${staged} new edition${staged === 1 ? "" : "s"} waiting${card.ask ? " · apply only when you are sure" : ""}` : `${card.rows.length} source${card.rows.length === 1 ? "" : "s"} watched`}>
      {card.rows.map((r) => <SourceRow key={`${r.source}-${r.id ?? "x"}`} row={r} ask={card.ask} />)}
    </Card>
  );
}
