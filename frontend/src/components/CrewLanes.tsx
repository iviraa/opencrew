import type { PlanBurst, PlanRow } from "../api";
import { monthYear } from "../format";

const time = (iso: string) => new Date(iso).getTime();

export default function CrewLanes({ rows, colors, selected }: { rows: PlanRow[]; colors: Record<string, string>; selected: string[] }) {
  if (!rows.length) return <div className="p-4 text-sm text-slate-400">Solve the joint plan to see crew lanes.</div>;
  const crews = [...new Set(rows.map((r) => r.crew))].sort();
  const task = (r: PlanRow) => [time(r.phases.find((p) => p.phase === "clearing")!.start), time(r.phases.find((p) => p.phase === "construction")!.end)];
  const bursts: (PlanBurst & { row: PlanRow })[] = rows.flatMap((r) => (r.bursts ?? []).map((b) => ({ ...b, row: r })));
  const resources = [...new Set(bursts.map((b) => b.resource))].sort((a, b) =>
    Number(bursts.some((x) => x.resource === b && x.shared)) - Number(bursts.some((x) => x.resource === a && x.shared)) || a.localeCompare(b));
  const ts = [...rows.flatMap((r) => [...task(r), time(r.filed_start), time(r.filed_end)]), ...bursts.flatMap((b) => [time(b.start), time(b.end)])];
  const [t0, t1] = [Math.min(...ts), Math.max(...ts)];
  const x = (t: number) => `${((t - t0) / (t1 - t0)) * 100}%`;
  const years: number[] = [];
  for (let y = new Date(t0).getFullYear() + 1; y <= new Date(t1).getFullYear(); y++) years.push(y);

  return (
    <div className="flex h-full flex-col bg-white">
      <div className="relative h-6 shrink-0 border-b border-slate-200 text-[10px] text-slate-400">
        <span className="absolute left-3 top-1 w-[150px] truncate" title="Solid bars: planned work in the joint plan. Dashed: the filed dates.">
          Crew lanes · <span className="inline-block h-2 w-3 rounded-sm border border-dashed border-slate-400 align-middle" /> filed
        </span>
        <div className="absolute inset-y-0 left-[160px] right-0">
          {years.map((y) => <span key={y} className="absolute top-1 -translate-x-1/2" style={{ left: x(new Date(y, 0, 1).getTime()) }}>{y}</span>)}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {crews.map((crew) => (
          <div key={crew} className="flex h-7 items-center border-b border-slate-50">
            <div className="w-[160px] shrink-0 truncate px-3 text-[11px] font-medium text-slate-700">{crew}</div>
            <div className="relative h-full flex-1 overflow-hidden">
              {rows.filter((r) => r.crew === crew).map((r) => {
                const [a, b] = task(r);
                const on = selected.includes(r.job_id);
                return (
                  <div key={r.job_id}>
                    <div className="absolute top-1 h-5 rounded-sm border border-dashed border-slate-300"
                      style={{ left: x(time(r.filed_start)), width: `calc(${x(time(r.filed_end))} - ${x(time(r.filed_start))})` }} />
                    <div title={`${r.name}\n${monthYear(new Date(a).toISOString())} → ${monthYear(new Date(b).toISOString())} · yard ${r.yard_label}${r.slip ? ` · ${r.slip} months late` : ""}${r.why ? `\n${r.why}` : ""}`}
                      className={`absolute top-1.5 h-4 truncate rounded-sm px-1 text-[9px] leading-4 text-white ${on ? "ring-2 ring-slate-900" : ""}`}
                      style={{ left: x(a), width: `max(4px, calc(${x(b)} - ${x(a)}))`, background: colors[r.org] ?? "#64748b" }}>
                      {r.name}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {resources.length > 0 && (
          <div className="sticky top-0 bg-slate-50 px-3 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            Specialty crews · shared ones serve both utilities
          </div>
        )}
        {resources.map((res) => {
          const items = bursts.filter((b) => b.resource === res);
          const shared = items.some((b) => b.shared);
          return (
            <div key={res} className={`flex h-6 items-center border-b border-slate-50 ${shared ? "bg-emerald-50/60" : ""}`}>
              <div className="w-[160px] shrink-0 truncate px-3 text-[11px] text-slate-700">{res}{shared && <b className="ml-1 text-emerald-700">shared</b>}</div>
              <div className="relative h-full flex-1 overflow-hidden">
                {items.map((b) => (
                  <div key={`${b.row.job_id}-${b.burst}`} title={`${b.label} at ${b.row.name}\n${b.start} → ${b.end}${b.partner ? `\nsame crew as ${b.partner}` : ""}`}
                    className={`absolute top-1 h-4 rounded-sm ${selected.includes(b.row.job_id) ? "ring-2 ring-slate-900" : ""}`}
                    style={{ left: x(time(b.start)), width: `max(5px, calc(${x(time(b.end))} - ${x(time(b.start))}))`, background: colors[b.row.org] ?? "#64748b" }} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
