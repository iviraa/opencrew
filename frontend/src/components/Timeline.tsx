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
    <div className="flex h-full flex-col bg-surface">
      <div className="relative h-9 shrink-0 border-b border-line text-[12px] text-faint">
        <div className="absolute left-4 top-1.5 flex items-center gap-1.5">
          <div className="inline-flex rounded-full bg-soft p-0.5 ring-1 ring-line">
            {[false, true].map((v) => (
              <button key={String(v)} onClick={() => setAll(v)} aria-pressed={all === v}
                className={`rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${all === v ? "bg-surface text-ink shadow-sm" : "text-muted"}`}>
                {v ? "All" : "Paired"}
              </button>
            ))}
          </div>
          <span className="ml-1 flex items-center gap-1.5 text-muted"><span className="inline-block h-3 w-5 rounded-full border-2 border-dashed border-faint" />earlier plan</span>
          {filter && (
            <button onClick={onClearFilter} className="rounded-full bg-desc-soft px-2.5 py-0.5 text-[12px] font-semibold text-desc">
              {filter.years ? `${filter.years[0]}–${filter.years[1]}` : "All years"}{filter.orgs ? `, ${filter.orgs.join(" and ").toUpperCase()}` : ""} ✕
            </button>
          )}
        </div>
        <div ref={axis} className="absolute inset-y-0 right-0 left-[260px]">
          {years.filter((_, i) => i % step === 0).map((y) => (
            <span key={y} className="absolute top-2 -translate-x-1/2 font-medium" style={{ left: x(new Date(y, 0, 1).getTime()) }}>{y}</span>
          ))}
        </div>
      </div>
      <div ref={box} className="thin-scroll relative flex-1 overflow-y-auto">
        <div className="pointer-events-none absolute inset-y-0 left-[260px] right-0">
          {years.map((y) => <div key={y} className="absolute inset-y-0 border-l border-soft" style={{ left: x(new Date(y, 0, 1).getTime()) }} />)}
          {Date.now() > t0 && Date.now() < t1 && <div className="absolute inset-y-0 border-l-2 border-dashed border-gpc/60" title="Today" style={{ left: x(Date.now()) }} />}
          {overlap && overlap[1] > overlap[0] && (
            <div className="absolute inset-y-0 rounded-md bg-crossing/10" style={{ left: x(overlap[0]), width: `calc(${x(overlap[1])} - ${x(overlap[0])})` }} />
          )}
        </div>
        {rows.length === 0 && <div className="px-4 py-5 text-[14px] text-muted">{jobs ? "No projects in the current list." : "Loading projects…"}</div>}
        {rows.map((r) => {
          const header = r.org !== lastOrg;
          lastOrg = r.org;
          const on = selKeys.has(r.key);
          return (
            <div key={r.key}>
              {header && <div className="sticky top-0 z-10 bg-surface/95 px-4 py-1 text-[13px] font-semibold backdrop-blur" style={{ color: r.color }}>{r.org}</div>}
              <div data-selected={on} data-key={r.key} onMouseEnter={() => onHover(r.key)} onMouseLeave={() => onHover(null)}
                className={`flex h-8 items-center ${r.key === hoverKey ? "bg-crew-soft" : on ? "bg-crossing-soft" : ""}`}>
                <div className={`w-[260px] shrink-0 truncate px-4 text-[13px] ${on ? "font-semibold text-ink" : "text-muted"}`} title={r.name}>{r.name}</div>
                <div className="relative h-full flex-1 overflow-hidden">
                  {r.bars.flatMap((b) => b.history ?? []).map((h) => (
                    <div key={h.observed_at} title={`Plan as of ${monthYear(h.observed_at)}: ${monthYear(h.start_at)} to ${monthYear(h.end_at)}`}
                      className="absolute top-1.5 h-5 rounded-full border-2 border-dashed"
                      style={{ left: x(time(h.start_at)), width: `calc(${x(time(h.end_at))} - ${x(time(h.start_at))})`, borderColor: r.color }} />
                  ))}
                  {r.bars.map((b) => (
                    <button key={b.id} onClick={() => pick(b)} title={`${b.phase ?? b.name}: ${monthYear(b.start_at)} to ${monthYear(b.end_at)}`}
                      className="absolute top-2.5 h-3 rounded-full transition hover:ring-2 hover:ring-ink/40"
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
