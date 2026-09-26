import { ChevronDown, ChevronUp, FileText, GitCompare, MapPin, Plus, Star, Undo2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../data";
import { ChartSvg } from "../generate/ChartCard";
import ReportCard from "../generate/ReportCard";
import type { Report } from "../generate/types";
import { CHANGE_KINDS, changeLabel, changesOf, type Change, type ChangeKind } from "./changes";
import KnobControl, { type PickPlace } from "./Knobs";
import { direction, findings, range, show, signed, unitOf, type Delta, type Finding, type Knob } from "./types";

const TONE = { good: "text-save", bad: "text-warn", flat: "text-muted" };

// set a knob value, following dotted names like "changes.0.months" into the params
function setPath(params: Record<string, unknown>, path: string, value: unknown) {
  const out = structuredClone(params) as Record<string, unknown>;
  const keys = path.split(".");
  let cur: Record<string, unknown> | unknown[] = out;
  keys.slice(0, -1).forEach((k) => { cur = (cur as Record<string, unknown>)[k] as Record<string, unknown> ?? ((cur as Record<string, unknown>)[k] = {}); });
  (cur as Record<string, unknown>)[keys[keys.length - 1]] = value;
  return out;
}

export type FindingCardProps = {
  finding: Finding; partners?: string[]; onOpen?: (overlapId: number) => void; onOverlay?: (f: Finding | null) => void;
  onPickPlace?: PickPlace; picking?: boolean; onCompare?: (f: Finding) => void; onChanged?: (f: Finding) => void; compact?: boolean;
};

// an experiment's result in the chat: before and after, the scenario stack, knobs to try again, and ways to keep or share it
export default function FindingCard({ finding: initial, partners = [], onOpen, onOverlay, onPickPlace, picking, onCompare, onChanged, compact }: FindingCardProps) {
  const [f, setF] = useState(initial);
  const [history, setHistory] = useState<Finding[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [why, setWhy] = useState(false);
  const [adding, setAdding] = useState<ChangeKind | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [pickingKnob, setPickingKnob] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [reportOk, setReportOk] = useState(true);

  useEffect(() => { findings.get(initial.id).then((fresh) => setF({ ...initial, ...fresh })).catch(() => {}); }, [initial.id]);  // a saved card refreshes itself; the stored copy stays if it can't

  const apply = (next: Finding) => { setHistory((h) => [...h, f]); setF(next); onOverlay?.(next); onChanged?.(next); };
  const run = async (kind: string, params: Record<string, unknown>) => {
    setBusy(true); setErr(null);
    try { apply(await findings.run(kind, params)); }
    catch (e) { setErr(e instanceof Error ? (e.message === "Not Found" ? "Experiments are not available on this server yet." : e.message) : String(e)); }
    finally { setBusy(false); }
  };
  const knob = (k: Knob, v: unknown) => run(f.kind, setPath(f.params, k.name, v));
  const stack = changesOf(f);
  const compose = (changes: Change[]) => run("compose", { changes, base_finding_id: f.id });
  const removeChange = (i: number) => { const rest = stack.filter((_, j) => j !== i); if (rest.length) compose(rest); };
  const addChange = () => {
    if (!adding) return;
    const params = Object.fromEntries(adding.knobs.map((k) => [k.name, draft[k.name] ?? k.value]));
    setAdding(null); setDraft({});
    compose([...stack, { kind: adding.kind, params }]);
  };
  const undo = () => { const prev = history[history.length - 1]; if (!prev) return; setHistory((h) => h.slice(0, -1)); setF(prev); onOverlay?.(prev); };
  const star = async () => {
    try { const r = await findings.star(f.id); setF((x) => ({ ...x, starred: "starred" in r ? r.starred : !x.starred })); }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const makeReport = async () => {
    try { setReport(await api.send<Report>("/api/app/report", "POST", { kind: "finding", id: f.id })); }
    catch { setReportOk(false); }
  };
  const overlapId = (() => { const raw = f.params.opportunity_id ?? f.params.overlap_id ?? f.params.id; const n = Number(String(raw ?? "").replace("#", "")); return Number.isFinite(n) && n > 0 ? n : null; })();
  const pickFor = (name: string): PickPlace | undefined => onPickPlace && ((cb) => { setPickingKnob(name); onPickPlace((lon, lat) => { setPickingKnob(null); cb(lon, lat); }); });
  const rows: Delta[] = f.deltas.length ? f.deltas : Object.entries(f.scenario.metrics).map(([metric, m]) => ({ metric, label: m.label ?? metric, base: f.base.metrics[metric]?.value ?? "", scenario: m.value, delta: 0, unit: m.unit }));
  const withOptions = (k: Knob) => (k.name === "partner" && !k.options?.length ? { ...k, options: partners } : k);

  return (
    <div className={`pop-in flex flex-col gap-1.5 rounded-2xl border-2 border-pen bg-white p-2 ${busy ? "opacity-70" : ""}`}>
      <div className="px-1">
        <div className="text-sm font-semibold leading-snug">{f.title}</div>
        {f.question && <div className="text-[11px] text-muted">{f.question}</div>}
      </div>

      <div className="flex flex-wrap items-center gap-1 px-1" aria-label="Scenario stack">
        {stack.map((c, i) => (
          <span key={i} className="flex items-center gap-1 rounded-full bg-grape-soft px-2 py-0.5 text-[11px] font-semibold text-grape">
            {changeLabel(c)}
            {stack.length > 1 && <button onClick={() => removeChange(i)} aria-label={`Remove ${changeLabel(c)}`} className="rounded-full hover:bg-white"><X size={11} /></button>}
          </span>
        ))}
        <button onClick={() => { setAdding(adding ? null : CHANGE_KINDS[0]); setDraft({}); }} aria-expanded={!!adding} className="flex items-center gap-0.5 rounded-full border-2 border-dashed border-line px-2 py-0.5 text-[11px] font-semibold text-muted hover:border-pen"><Plus size={11} /> Add a change</button>
      </div>
      {adding && (
        <div className="flex flex-col gap-1.5 rounded-xl bg-soft px-2 py-2">
          <select value={adding.kind} aria-label="Kind of change" onChange={(e) => { setAdding(CHANGE_KINDS.find((c) => c.kind === e.target.value) ?? null); setDraft({}); }} className="rounded-full border-2 border-line bg-white px-2 py-0.5 text-[11px] font-semibold">
            {CHANGE_KINDS.map((c) => <option key={c.kind} value={c.kind}>{c.label}</option>)}
          </select>
          {adding.knobs.map((k) => <KnobControl key={k.name} knob={withOptions({ ...k, value: draft[k.name] ?? k.value })} onChange={(v) => setDraft((d) => ({ ...d, [k.name]: v }))} onPickPlace={pickFor(`new.${k.name}`)} picking={picking && pickingKnob === `new.${k.name}`} />)}
          <div className="flex gap-1.5">
            <button onClick={addChange} disabled={busy} className="rounded-full bg-grape px-2.5 py-0.5 text-[11px] font-semibold text-white disabled:opacity-40">Apply</button>
            <button onClick={() => setAdding(null)} className="rounded-full border-2 border-line px-2.5 py-0.5 text-[11px] font-semibold">Cancel</button>
          </div>
        </div>
      )}

      <div className="rounded-xl border-2 border-line">
        <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-faint"><span>Metric</span><span>Before</span><span>After</span><span className="text-right">Change</span></div>
        {rows.map((d) => {
          const u = unitOf(d.metric, d.unit), tone = direction(d.metric, d.delta);
          const bm = f.base.metrics[d.metric], sm = f.scenario.metrics[d.metric];
          return (
            <div key={d.metric} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 border-t border-line px-2 py-1 text-[11px]">
              <span className="truncate text-muted">{d.label}</span>
              <span className="text-muted">{bm && bm.low != null ? range({ ...bm, unit: bm.unit ?? u }) : show(d.base, u)}</span>
              <span className="font-semibold">{sm && sm.low != null ? range({ ...sm, unit: sm.unit ?? u }) : show(d.scenario, u)}</span>
              <span className={`text-right font-semibold ${TONE[tone]}`}>{typeof d.delta === "number" && d.delta === 0 ? "same" : signed(d.delta, u)}{d.pct != null && d.pct !== 0 ? ` (${d.pct > 0 ? "+" : ""}${Math.round(d.pct)}%)` : ""}</span>
            </div>
          );
        })}
      </div>

      {f.chart && <div className="px-1"><div className="text-[11px] font-semibold">{f.chart.title}</div><ChartSvg chart={f.chart} onHover={() => {}} /></div>}

      {f.knobs.length > 0 && (
        <div className="flex flex-col gap-1 px-1">
          {f.knobs.map((k) => <KnobControl key={k.name} knob={withOptions(k)} onChange={(v) => knob(k, v)} onPickPlace={pickFor(k.name)} picking={picking && pickingKnob === k.name} />)}
        </div>
      )}

      {f.notes.length > 0 && <ul className="flex flex-col gap-0.5 px-1 text-xs">{f.notes.map((n, i) => <li key={i} className="leading-snug">{n}</li>)}</ul>}
      {f.evidence.length > 0 && (
        <div className="px-1">
          <button onClick={() => setWhy(!why)} aria-expanded={why} className="flex items-center gap-1 text-[11px] font-semibold text-grape">{why ? <ChevronUp size={12} /> : <ChevronDown size={12} />} Why</button>
          {why && <ul className="mt-0.5 flex flex-col gap-0.5 text-[11px] text-muted">{f.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1 px-1">
        <button onClick={star} aria-pressed={!!f.starred} className={`flex items-center gap-1 rounded-full border-2 px-2 py-0.5 text-[11px] font-semibold ${f.starred ? "border-pen bg-crew-soft" : "border-line hover:border-pen"}`}><Star size={12} fill={f.starred ? "#ffb020" : "none"} /> {f.starred ? "Saved" : "Star"}</button>
        {onCompare && <button onClick={() => onCompare(f)} className="flex items-center gap-1 rounded-full border-2 border-line px-2 py-0.5 text-[11px] font-semibold hover:border-pen"><GitCompare size={12} /> Compare</button>}
        {reportOk && !report && <button onClick={makeReport} className="flex items-center gap-1 rounded-full border-2 border-line px-2 py-0.5 text-[11px] font-semibold hover:border-pen"><FileText size={12} /> Report</button>}
        {(overlapId != null || onOverlay) && (
          <button onClick={() => { onOverlay?.(f); if (overlapId != null) onOpen?.(overlapId); }} className="flex items-center gap-1 rounded-full border-2 border-line px-2 py-0.5 text-[11px] font-semibold hover:border-pen"><MapPin size={12} /> Open on map</button>
        )}
        {history.length > 0 && <button onClick={undo} className="flex items-center gap-1 rounded-full border-2 border-line px-2 py-0.5 text-[11px] font-semibold hover:border-pen"><Undo2 size={12} /> Undo</button>}
      </div>
      {report && <ReportCard report={report} />}
      {!compact && f.sources.length > 0 && <div className="px-1 text-[10px] text-faint">{f.sources.join(" · ")}</div>}
      {err && <p className="px-1 text-[11px] text-warn">{err}</p>}
    </div>
  );
}
