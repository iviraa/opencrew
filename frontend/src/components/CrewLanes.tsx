import type { PlanBurst, PlanRow } from "../api";
import { monthYear } from "../format";

const time = (iso: string) => new Date(iso).getTime();
const LABEL_W = 180;

export default function CrewLanes({ rows, colors, selected }: { rows: PlanRow[]; colors: Record<string, string>; selected: string[] }) {
  if (!rows.length) return <div className="p-5 text-[14px] text-muted">Plan the joint schedule to see which crew goes where.</div>;
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
    <div className="flex h-full flex-col bg-surface">
      <div className="relative h-8 shrink-0 border-b border-line text-[12px] text-faint">
        <span className="absolute left-4 top-1.5 flex items-center gap-2 text-muted" style={{ width: LABEL_W - 20 }}>
          <span className="inline-block h-3 w-5 rounded-full border-2 border-dashed border-faint" /> filed dates
        </span>
        <div className="absolute inset-y-0 right-0" style={{ left: LABEL_W }}>
          {years.map((y) => <span key={y} className="absolute top-1.5 -translate-x-1/2" style={{ left: x(new Date(y, 0, 1).getTime()) }}>{y}</span>)}
        </div>
      </div>
      <div className="thin-scroll relative flex-1 overflow-y-auto">
        <div className="pointer-events-none absolute inset-y-0 right-0" style={{ left: LABEL_W }}>
          {years.map((y) => <div key={y} className="absolute inset-y-0 border-l border-soft" style={{ left: x(new Date(y, 0, 1).getTime()) }} />)}
        </div>
        {crews.map((crew) => (
          <div key={crew} className="relative flex h-9 items-center">
            <div className="shrink-0 truncate px-4 text-[13px] font-semibold text-ink" style={{ width: LABEL_W }}>{crew}</div>
            <div className="relative h-full flex-1 overflow-hidden">
              {rows.filter((r) => r.crew === crew).map((r) => {
                const [a, b] = task(r);
                const on = selected.includes(r.job_id);
                return (
                  <div key={r.job_id}>
                    <div className="absolute top-1.5 h-6 rounded-full border-2 border-dashed border-line"
                      style={{ left: x(time(r.filed_start)), width: `calc(${x(time(r.filed_end))} - ${x(time(r.filed_start))})` }} />
                    <div title={`${r.name}\n${monthYear(new Date(a).toISOString())} to ${monthYear(new Date(b).toISOString())}\nyard ${r.yard_label}${r.slip ? `\n${r.slip} months late` : ""}${r.why ? `\n${r.why}` : ""}`}
                      className={`absolute top-2 h-5 truncate rounded-full px-2.5 text-[12px] font-semibold leading-5 text-white ${on ? "ring-[3px] ring-ink/70" : ""}`}
                      style={{ left: x(a), width: `max(8px, calc(${x(b)} - ${x(a)}))`, background: colors[r.org] ?? "#8a94b0" }}>
                      {r.name}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {resources.length > 0 && (
          <div className="sticky top-0 z-10 bg-soft/95 px-4 py-1.5 text-[13px] font-semibold text-muted backdrop-blur">
            Specialty crews <span className="font-normal">(green lanes serve both utilities)</span>
          </div>
        )}
        {resources.map((res) => {
          const items = bursts.filter((b) => b.resource === res);
          const shared = items.some((b) => b.shared);
          return (
            <div key={res} className={`relative flex h-8 items-center ${shared ? "bg-save-soft/70" : ""}`}>
              <div className="shrink-0 truncate px-4 text-[13px] text-ink" style={{ width: LABEL_W }}>
                {res}{shared && <span className="ml-1.5 rounded-full bg-save px-2 py-0.5 text-[11px] font-semibold text-white">shared</span>}
              </div>
              <div className="relative h-full flex-1 overflow-hidden">
                {items.map((b) => (
                  <div key={`${b.row.job_id}-${b.burst}`} title={`${b.label} at ${b.row.name}\n${b.start} to ${b.end}${b.partner ? `\nsame crew as ${b.partner}` : ""}`}
                    className={`absolute top-2 h-4 rounded-full ${selected.includes(b.row.job_id) ? "ring-[3px] ring-ink/70" : ""}`}
                    style={{ left: x(time(b.start)), width: `max(8px, calc(${x(time(b.end))} - ${x(time(b.start))}))`, background: colors[b.row.org] ?? "#8a94b0" }} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
