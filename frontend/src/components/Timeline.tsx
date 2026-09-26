import { useEffect, useMemo, useRef, useState } from "react";
import type { Job, JobCollection, Opportunity } from "../api";
import { monthYear } from "../format";

type Props = {
  jobs: JobCollection | null;
  opportunities: Opportunity[];
  selected: Opportunity | null;
  onSelect: (id: number) => void;
  hoverKey: string | null;
  scrollToHover: boolean;
  onHover: (key: string | null) => void;
  filter?: { years: [number, number] | null; orgs: string[] | null } | null;
  onClearFilter?: () => void;
};

type Row = { key: string; org: string; color: string; name: string; bars: Job[] };

const PHASE_SHADE: Record<string, number> = { "survey & permitting": 0.35, clearing: 0.55, construction: 0.9, energization: 0.65 };
const time = (iso: string) => new Date(iso).getTime();

export default function Timeline({ jobs, opportunities, selected, onSelect, hoverKey, scrollToHover, onHover, filter, onClearFilter }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const axis = useRef<HTMLDivElement>(null);
  const [axisWidth, setAxisWidth] = useState(800);
  const [all, setAll] = useState(false);

  useEffect(() => {
    if (!axis.current) return;
    const ro = new ResizeObserver(([e]) => setAxisWidth(e.contentRect.width));
    ro.observe(axis.current);
    return () => ro.disconnect();
  }, []);
  const byId = useMemo(() => new Map(jobs?.features.map((f) => [f.properties.id, f.properties]) ?? []), [jobs]);
  const rowKey = (j: Job) => j.parent_job_id ?? j.id;

  const rows = useMemo(() => {
    const wanted = new Set(opportunities.flatMap((o) => [o.job_a, o.job_b]).map((id) => byId.get(id)).filter(Boolean).map((j) => rowKey(j!)));
    const map = new Map<string, Row>();
    for (const j of byId.values()) {
      const key = rowKey(j);
      if (!all && !wanted.has(key)) continue;
      if (filter?.orgs && !filter.orgs.includes(j.org_id)) continue;
      const row = map.get(key) ?? { key, org: j.org_name, color: j.color, name: j.name, bars: [] };
      row.bars.push(j);
      map.set(key, row);
    }
    return [...map.values()].sort((a, b) => a.org.localeCompare(b.org) || time(a.bars[0].start_at) - time(b.bars[0].start_at));
  }, [opportunities, byId, all, filter]);

  const [t0, t1] = useMemo(() => {
    if (filter?.years) return [new Date(filter.years[0], 0, 1).getTime(), new Date(filter.years[1] + 1, 0, 1).getTime()];
    const ts = rows.flatMap((r) => r.bars.flatMap((b) => [b, ...(b.history ?? [])]).flatMap((b) => [time(b.start_at), time(b.end_at)]));
    return ts.length ? [Math.min(...ts), Math.max(...ts)] : [Date.now() - 3e10, Date.now() + 3e10];
  }, [rows, filter]);
  const x = (t: number) => `${((t - t0) / (t1 - t0)) * 100}%`;
  const years = [];
  for (let y = new Date(t0).getFullYear() + 1; y <= new Date(t1).getFullYear(); y++) years.push(y);
  const step = Math.max(1, Math.ceil((years.length * 36) / Math.max(axisWidth, 1)));  // about 36px per year label

  const sel = selected ? [byId.get(selected.job_a), byId.get(selected.job_b)] : [];
  const selKeys = new Set(sel.filter(Boolean).map((j) => rowKey(j!)));
  const overlap = sel[0] && sel[1] ? [Math.max(time(sel[0].start_at), time(sel[1].start_at)), Math.min(time(sel[0].end_at), time(sel[1].end_at))] : null;

  useEffect(() => {
    box.current?.querySelector("[data-selected='true']")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  useEffect(() => {
    if (!scrollToHover || !hoverKey) return;
    box.current?.querySelector(`[data-key="${CSS.escape(hoverKey)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [hoverKey, scrollToHover]);

  const pick = (j: Job) => {
    const best = opportunities.filter((o) => o.job_a === j.id || o.job_b === j.id).sort((a, b) => b.score - a.score)[0];
    if (best) onSelect(best.id);
  };

  let lastOrg = "";
  return (
    <div className="flex h-full flex-col bg-white">
      <div className="relative h-6 shrink-0 border-b border-slate-200 text-[10px] text-slate-400">
        <div className="absolute left-3 top-0.5 flex gap-2">
          {[false, true].map((v) => (
            <button key={String(v)} onClick={() => setAll(v)} className={`rounded px-1.5 py-0.5 ${all === v ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
              {v ? "All projects" : "In opportunities"}
            </button>
          ))}
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 rounded-sm border border-dashed border-slate-400" /> earlier plan</span>
          {filter && (
            <button onClick={onClearFilter} className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700 ring-1 ring-blue-200">
              {filter.years ? `${filter.years[0]}–${filter.years[1]}` : "all years"}{filter.orgs ? ` · ${filter.orgs.join(", ").toUpperCase()}` : ""} ✕
            </button>
          )}
        </div>
        <div ref={axis} className="absolute inset-y-0 left-[260px] right-0">
          {years.filter((_, i) => i % step === 0).map((y) => (
            <span key={y} className="absolute top-1 -translate-x-1/2" style={{ left: x(new Date(y, 0, 1).getTime()) }}>{y}</span>
          ))}
        </div>
      </div>
      <div ref={box} className="relative flex-1 overflow-y-auto">
        <div className="pointer-events-none absolute inset-y-0 left-[260px] right-0">
          {years.map((y) => <div key={y} className="absolute inset-y-0 border-l border-slate-100" style={{ left: x(new Date(y, 0, 1).getTime()) }} />)}
          {Date.now() > t0 && Date.now() < t1 && <div className="absolute inset-y-0 border-l-2 border-dashed border-rose-400" style={{ left: x(Date.now()) }} />}
          {overlap && overlap[1] > overlap[0] && (
            <div className="absolute inset-y-0 bg-violet-500/10" style={{ left: x(overlap[0]), width: `calc(${x(overlap[1])} - ${x(overlap[0])})` }} />
          )}
        </div>
        {rows.length === 0 && <div className="px-3 py-4 text-xs text-slate-400">{jobs ? "No projects in the current list." : "Loading projects…"}</div>}
        {rows.map((r) => {
          const header = r.org !== lastOrg;
          lastOrg = r.org;
          const on = selKeys.has(r.key);
          return (
            <div key={r.key}>
              {header && <div className="sticky top-0 z-10 bg-slate-50 px-3 py-0.5 text-[10px] font-semibold uppercase tracking-wide" style={{ color: r.color }}>{r.org}</div>}
              <div data-selected={on} data-key={r.key} onMouseEnter={() => onHover(r.key)} onMouseLeave={() => onHover(null)}
                className={`flex h-6 items-center ${r.key === hoverKey ? "bg-amber-50" : on ? "bg-violet-50" : ""}`}>
                <div className={`w-[260px] shrink-0 truncate px-3 text-[11px] ${on ? "font-semibold text-slate-900" : "text-slate-600"}`} title={r.name}>{r.name}</div>
                <div className="relative h-full flex-1 overflow-hidden">
                  {r.bars.flatMap((b) => b.history ?? []).map((h) => (
                    <div key={h.observed_at} title={`Plan as of ${monthYear(h.observed_at)}: ${monthYear(h.start_at)} → ${monthYear(h.end_at)}`}
                      className="absolute top-1 h-4 rounded-sm border border-dashed"
                      style={{ left: x(time(h.start_at)), width: `calc(${x(time(h.end_at))} - ${x(time(h.start_at))})`, borderColor: r.color }} />
                  ))}
                  {r.bars.map((b) => (
                    <button key={b.id} onClick={() => pick(b)} title={`${b.phase ?? b.name}: ${monthYear(b.start_at)} → ${monthYear(b.end_at)}`}
                      className="absolute top-1.5 h-3 rounded-sm hover:ring-2 hover:ring-slate-400"
                      style={{ left: x(time(b.start_at)), width: `max(3px, calc(${x(time(b.end_at))} - ${x(time(b.start_at))}))`, background: r.color,
                        opacity: (b.phase ? PHASE_SHADE[b.phase] : 0.85) * (selected && !on ? 0.5 : 1) }} />
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
