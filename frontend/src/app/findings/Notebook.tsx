import { Combine, GitCompare, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ago } from "../data";
import { PanelHeader } from "../panels";
import { changesOf, combine, kindLabel } from "./changes";
import CompareCard from "./CompareCard";
import FindingCard, { type FindingCardProps } from "./FindingCard";
import { findings, headline, type Comparison, type Finding } from "./types";

// the starred findings: open one, compare two, or combine their scenario stacks into a new experiment
export function NotebookPanel({ onBack, onOpen, onCombined, preselect }: { onBack: () => void; onOpen: (f: Finding) => void; onCombined: (f: Finding) => void; preselect?: number }) {
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

  return (
    <>
      <PanelHeader title="Findings" sub={list ? `${list.length} saved experiment${list.length === 1 ? "" : "s"}` : "Loading..."} onBack={onBack} />
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
