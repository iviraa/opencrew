import { FileText, FlaskConical, GitCompare, MapPin, Plus, SlidersHorizontal, Star, Undo2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../data";
import { ChartSvg } from "../generate/ChartCard";
import ReportCard from "../generate/ReportCard";
import type { Report } from "../generate/types";
import { Card, Chip, Drawer, Lead, Note, Pill, RefLink, Row, StatRow, signedPct, signedUnit, withUnit } from "../ui";
import { CHANGE_KINDS, changesOf, type Change, type ChangeKind } from "./changes";
import KnobControl, { type PickPlace } from "./Knobs";
import { describeChange, findingSentence, movers } from "./prose";
import { direction, findings, overlapIdOf, range, show, signed, unitOf, type Delta, type Finding, type Knob } from "./types";

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

// an experiment's result in the chat: what it found in a sentence, the numbers that moved, and drawers for the detail and the knobs
export default function FindingCard({ finding: initial, partners = [], onOpen, onOverlay, onPickPlace, picking, onCompare, onChanged, compact }: FindingCardProps) {
  const [f, setF] = useState(initial);
  const [history, setHistory] = useState<Finding[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
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
  const overlapId = overlapIdOf(f);
  const pickFor = (name: string): PickPlace | undefined => onPickPlace && ((cb) => { setPickingKnob(name); onPickPlace((lon, lat) => { setPickingKnob(null); cb(lon, lat); }); });
  const rows: Delta[] = f.deltas.length ? f.deltas : Object.entries(f.scenario.metrics).map(([metric, m]) => ({ metric, label: m.label ?? metric, base: f.base.metrics[metric]?.value ?? "", scenario: m.value, delta: 0, unit: m.unit }));
  const withOptions = (k: Knob) => (k.name === "partner" && !k.options?.length ? { ...k, options: partners } : k);
  const top = movers(f.deltas).slice(0, 3);
  const knobCount = f.knobs.length + (stack.length > 1 ? stack.length : 0);

  return (
    <Card icon={<FlaskConical size={15} />} title={f.title} busy={busy}
      sub={<>{f.question && <span>{f.question}</span>}{overlapId != null && <> · <RefLink id={overlapId} onOpen={onOpen} /></>}</>}
      right={<Pill onClick={star} pressed={!!f.starred} title={f.starred ? "Saved in the notebook" : "Save to the notebook"} icon={<Star size={12} fill={f.starred ? "#ffb020" : "none"} />} />}>
      <Lead>{findingSentence(f, stack)}</Lead>
      {top.length > 0 && (
        <StatRow items={top.map((d) => { const u = unitOf(d.metric, d.unit); return {
          label: d.label, value: withUnit(d.scenario as number, u), tone: direction(d.metric, d.delta),
          note: `${signedUnit(Number(d.delta), u)}${d.pct != null && d.pct !== 0 ? ` · ${signedPct(d.pct)}` : ""}`,
        }; })} />
      )}

      <Drawer title="Details" summary={`${rows.length} metric${rows.length === 1 ? "" : "s"} before and after${f.chart ? " · chart" : ""}${f.evidence.length ? " · why" : ""}`}>
        <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 text-[10px] font-semibold uppercase tracking-wide text-faint"><span>Metric</span><span>Before</span><span>After</span><span className="text-right">Change</span></div>
        {rows.map((d) => {
          const u = unitOf(d.metric, d.unit), tone = direction(d.metric, d.delta);
          const bm = f.base.metrics[d.metric], sm = f.scenario.metrics[d.metric];
          return (
            <div key={d.metric} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 border-t border-line pt-1 text-[11px] tabular-nums">
              <span className="truncate text-muted">{d.label}</span>
              <span className="text-muted">{bm && bm.low != null ? range({ ...bm, unit: bm.unit ?? u }) : show(d.base, u)}</span>
              <span className="font-semibold">{sm && sm.low != null ? range({ ...sm, unit: sm.unit ?? u }) : show(d.scenario, u)}</span>
              <span className={`text-right font-semibold ${TONE[tone]}`}>{typeof d.delta === "number" && d.delta === 0 ? "same" : signed(d.delta, u)}{d.pct != null && d.pct !== 0 ? ` (${signedPct(d.pct)})` : ""}</span>
            </div>
          );
        })}
        {f.chart && <div className="pt-1"><div className="text-[11px] font-semibold">{f.chart.title}</div><ChartSvg chart={f.chart} onHover={() => {}} /></div>}
        {f.notes.length > 0 && <ul className="flex list-disc flex-col gap-0.5 pl-4 text-[11px] leading-snug">{f.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
        {f.evidence.length > 0 && (
          <div className="pt-0.5">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-faint">Why</div>
            <ul className="mt-0.5 flex list-disc flex-col gap-0.5 pl-4 text-[11px] leading-snug text-muted">{f.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
          </div>
        )}
        {!compact && f.sources.length > 0 && <Note>Sources: {f.sources.join(" · ")}</Note>}
      </Drawer>

      <Drawer title="Adjust the scenario" icon={<SlidersHorizontal size={13} />} summary={stack.map(describeChange).join(" · ")} defaultOpen={false}>
        <Row>
          {stack.map((c, i) => (
            <Chip key={i} tone="info">
              {describeChange(c)}
              {stack.length > 1 && <button onClick={() => removeChange(i)} aria-label={`Remove: ${describeChange(c)}`} className="rounded-full hover:bg-white"><X size={11} /></button>}
            </Chip>
          ))}
          <button onClick={() => { setAdding(adding ? null : CHANGE_KINDS[0]); setDraft({}); }} aria-expanded={!!adding} className="inline-flex items-center gap-0.5 rounded-full border-2 border-dashed border-line px-2 py-0.5 text-[11px] font-semibold text-muted hover:border-pen"><Plus size={11} /> Add a change</button>
        </Row>
        {adding && (
          <div className="flex flex-col gap-1.5 rounded-xl bg-soft px-2 py-2">
            <select value={adding.kind} aria-label="Kind of change" onChange={(e) => { setAdding(CHANGE_KINDS.find((c) => c.kind === e.target.value) ?? null); setDraft({}); }} className="rounded-full border-2 border-line bg-white px-2 py-0.5 text-[11px] font-semibold">
              {CHANGE_KINDS.map((c) => <option key={c.kind} value={c.kind}>{c.label}</option>)}
            </select>
            {adding.knobs.map((k) => <KnobControl key={k.name} knob={withOptions({ ...k, value: draft[k.name] ?? k.value })} onChange={(v) => setDraft((d) => ({ ...d, [k.name]: v }))} onPickPlace={pickFor(`new.${k.name}`)} picking={picking && pickingKnob === `new.${k.name}`} />)}
            <Row>
              <Pill primary onClick={addChange} disabled={busy}>Apply</Pill>
              <Pill onClick={() => setAdding(null)}>Cancel</Pill>
            </Row>
          </div>
        )}
        {f.knobs.length > 0 && (
          <div className="flex flex-col gap-1 pt-0.5">
            {f.knobs.map((k) => <KnobControl key={k.name} knob={withOptions(k)} onChange={(v) => knob(k, v)} onPickPlace={pickFor(k.name)} picking={picking && pickingKnob === k.name} />)}
          </div>
        )}
        {!f.knobs.length && !adding && <Note>{knobCount ? "Remove a change above or add another." : "Add a change to build on this result."}</Note>}
      </Drawer>

      <Row>
        {onCompare && <Pill onClick={() => onCompare(f)} icon={<GitCompare size={12} />}>Compare</Pill>}
        {reportOk && !report && <Pill onClick={makeReport} icon={<FileText size={12} />}>Report</Pill>}
        {(overlapId != null || onOverlay) && <Pill onClick={() => { onOverlay?.(f); if (overlapId != null) onOpen?.(overlapId); }} icon={<MapPin size={12} />}>On the map</Pill>}
        {history.length > 0 && <Pill onClick={undo} icon={<Undo2 size={12} />}>Undo</Pill>}
      </Row>
      {report && <ReportCard report={report} />}
      {err && <Note tone="warn">{err}</Note>}
    </Card>
  );
}
