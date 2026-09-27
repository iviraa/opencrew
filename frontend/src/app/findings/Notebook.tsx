import { Combine, GitCompare, MapPin, StickyNote, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ago } from "../data";
import { PanelHeader } from "../panels";
import { notesApi, type Note } from "../workspace/types";
import { changesOf, combine, kindLabel } from "./changes";
import CompareCard from "./CompareCard";
import FindingCard, { type FindingCardProps } from "./FindingCard";
import { findings, headline, type Comparison, type Finding } from "./types";

const targetLabel = (n: Note) => (n.target_kind === "overlap" ? `Overlap #${n.target_id}` : n.target_kind === "project" ? `Project ${n.target_id}` : n.target_kind === "general" ? "General" : `${n.target_kind} ${n.target_id}`);

// the team's notes, grouped by what they are about; an overlap's group opens its detail panel
function NotesList({ onOpenOverlap }: { onOpenOverlap?: (id: number) => void }) {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [about, setAbout] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => notesApi.all().then(setNotes).catch((e) => { setNotes([]); setErr(e instanceof Error ? e.message : String(e)); });
  useEffect(() => { refresh(); }, []);
  const add = async () => {
    if (!text.trim()) return;
    const oid = about.trim().replace("#", "");
    setBusy(true); setErr(null);
    try { await notesApi.add(oid ? "overlap" : "general", oid || "general", text); setText(""); setAbout(""); await refresh(); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const groups = new Map<string, Note[]>();
  (notes ?? []).forEach((n) => { const k = `${n.target_kind}:${n.target_id}`; groups.set(k, [...(groups.get(k) ?? []), n]); });
  return (
    <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
      <form onSubmit={(e) => { e.preventDefault(); add(); }} className="card-still flex flex-col gap-1.5 px-3 py-2">
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="Write a note for the team"
          className="w-full resize-none rounded-xl bg-soft px-2.5 py-1.5 text-sm outline-none focus:bg-grape-soft/40" />
        <div className="flex items-center gap-1.5">
          <input value={about} onChange={(e) => setAbout(e.target.value)} placeholder="about #overlap (optional)" inputMode="numeric"
            className="min-w-0 flex-1 rounded-full border-2 border-line bg-white px-3 py-1 text-xs outline-none focus:border-pen" />
          <button disabled={busy || !text.trim()} className="rounded-full bg-grape px-3 py-1 text-xs font-semibold text-white disabled:opacity-40">Add note</button>
        </div>
      </form>
      {[...groups.entries()].map(([key, ns]) => {
        const first = ns[0], oid = first.target_kind === "overlap" ? Number(first.target_id) : NaN;
        return (
          <div key={key} className="card-still flex flex-col gap-1 px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-faint">{targetLabel(first)}</span>
              <span className="flex-1" />
              {onOpenOverlap && Number.isFinite(oid) && (
                <button onClick={() => onOpenOverlap(oid)} className="flex items-center gap-1 rounded-full border-2 border-line px-2 py-0.5 text-[11px] font-semibold hover:border-pen"><MapPin size={11} /> Open</button>
              )}
            </div>
            {ns.map((n) => (
              <div key={n.id} className="flex items-start gap-2 rounded-xl bg-soft px-2.5 py-1.5">
                <p className="min-w-0 flex-1 text-sm leading-snug">{n.text}<span className="ml-1.5 whitespace-nowrap text-[11px] text-faint">{n.when}</span></p>
                <button onClick={() => notesApi.remove(n.id).then(refresh)} aria-label="Delete note" className="mt-0.5 text-faint hover:text-warn"><Trash2 size={12} /></button>
              </div>
            ))}
          </div>
        );
      })}
      {notes && !notes.length && <p className="px-2 py-6 text-center text-sm text-muted">No notes yet. Ask Crewly to note something, or add one on an overlap's detail panel.</p>}
      {err && <p className="pt-1 text-xs text-warn">{err}</p>}
    </div>
  );
}

// the notebook: the team's notes and the starred findings (open one, compare two, or combine their scenario stacks)
export function NotebookPanel({ onBack, onOpen, onCombined, preselect, onOpenOverlap }: {
  onBack: () => void; onOpen: (f: Finding) => void; onCombined: (f: Finding) => void; preselect?: number; onOpenOverlap?: (id: number) => void;
}) {
  const [tab, setTab] = useState<"notes" | "findings">(preselect != null ? "findings" : "notes");
  const [list, setList] = useState<Finding[] | null>(null);
  const [picked, setPicked] = useState<number[]>(preselect != null ? [preselect] : []);
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { findings.starred().then(setList).catch((e) => { setList([]); setErr(e instanceof Error ? (e.message === "Not Found" ? "The notebook is not available on this server yet." : e.message) : String(e)); }); }, []);

  const toggle = (id: number) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)));
  const [a, b] = picked;
  const compare = async () => {
    setBusy(true); setErr(null);
    try { setCmp(await findings.compare(a, b)); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const merge = async () => {
    const fa = list?.find((f) => f.id === a), fb = list?.find((f) => f.id === b);
    if (!fa || !fb) return;
    setBusy(true); setErr(null);
    try { onCombined(await findings.run("compose", { changes: combine(changesOf(fa), changesOf(fb)), base_finding_id: fa.id })); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  const remove = async (id: number) => {
    try { await findings.remove(id); setList((l) => l?.filter((f) => f.id !== id) ?? null); setPicked((p) => p.filter((x) => x !== id)); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const tabs = (
    <div className="mb-2 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
      {([["notes", "Notes"], ["findings", "Findings"]] as const).map(([k, label]) => (
        <button key={k} onClick={() => setTab(k)} aria-pressed={tab === k} className={`flex flex-1 items-center justify-center gap-1 rounded-full px-2 py-1 ${tab === k ? "bg-white shadow-sm" : "text-muted"}`}>
          {k === "notes" ? <StickyNote size={12} /> : <GitCompare size={12} />} {label}
        </button>
      ))}
    </div>
  );
  if (tab === "notes") {
    return (
      <>
        <PanelHeader title="Notebook" sub="Notes the team saved, and starred findings" onBack={onBack} />
        {tabs}
        <NotesList onOpenOverlap={onOpenOverlap} />
      </>
    );
  }
  return (
    <>
      <PanelHeader title="Notebook" sub={list ? `${list.length} saved experiment${list.length === 1 ? "" : "s"}` : "Loading..."} onBack={onBack} />
      {tabs}
      {picked.length === 2 && (
        <div className="mb-2 flex gap-1.5">
          <button onClick={compare} disabled={busy} className="flex flex-1 items-center justify-center gap-1 rounded-full bg-grape px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-40"><GitCompare size={13} /> Compare</button>
          <button onClick={merge} disabled={busy} className="flex flex-1 items-center justify-center gap-1 rounded-full border-2 border-pen px-2.5 py-1 text-xs font-semibold disabled:opacity-40"><Combine size={13} /> Combine</button>
        </div>
      )}
      {picked.length === 1 && <p className="mb-2 text-[11px] text-muted">Pick one more to compare or combine.</p>}
      {cmp && <div className="mb-2"><CompareCard comparison={cmp} /></div>}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1 overflow-y-auto pr-2">
        {list?.map((f) => (
          <div key={f.id} className={`flex items-start gap-2 rounded-2xl px-2 py-2 hover:bg-soft ${picked.includes(f.id) ? "bg-grape-soft" : ""}`}>
            <input type="checkbox" checked={picked.includes(f.id)} onChange={() => toggle(f.id)} aria-label={`Pick ${f.title}`} className="mt-1 accent-grape" />
            <button onClick={() => onOpen(f)} className="min-w-0 flex-1 text-left">
              <span className="line-clamp-2 text-sm font-semibold leading-snug">{f.title}</span>
              <span className="block text-xs text-muted">{f.kind === "compose" ? `${changesOf(f).length} changes` : kindLabel(f.kind)} · {ago(f.created_at)}</span>
              <span className="block text-xs font-semibold text-grape">{headline(f)}</span>
            </button>
            <button onClick={() => remove(f.id)} aria-label={`Delete ${f.title}`} className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted hover:bg-white hover:text-warn"><Trash2 size={14} /></button>
          </div>
        ))}
        {list && !list.length && <p className="px-2 py-6 text-center text-sm text-muted">No saved findings yet. Star one from the chat.</p>}
      </div>
      {err && <p className="pt-1 text-xs text-warn">{err}</p>}
    </>
  );
}

// one finding in the right quarter, from the notebook or a chat card's "Open on map"
export function FindingPanel({ id, initial, onBack, ...rest }: { id: number; initial?: Finding; onBack: () => void } & Omit<FindingCardProps, "finding" | "compact">) {
  const [f, setF] = useState<Finding | null>(initial ?? null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { if (!initial) findings.get(id).then(setF).catch((e) => setErr(e instanceof Error ? e.message : String(e))); }, [id, initial]);
  return (
    <>
      <PanelHeader title={f?.title ?? "Finding"} sub={f?.question} onBack={onBack} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col overflow-y-auto pr-2 pb-16">
        {f ? <FindingCard finding={f} {...rest} /> : <p className="text-sm text-muted">{err ?? <span className="dots">Loading</span>}</p>}
      </div>
    </>
  );
}
