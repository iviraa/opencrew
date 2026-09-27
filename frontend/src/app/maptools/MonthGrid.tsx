import { CalendarRange, Map as MapIcon } from "lucide-react";
import { useMemo } from "react";
import { colorFor } from "../data";
import type { Timeline } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ym = (s: string) => s.slice(0, 7);

// a calendar of build windows: one lane per project, months across, our lanes first; takes the map's place while open
export default function MonthGrid({ timeline, onPick, onBack }: { timeline: Timeline; onPick: (id: string, mine: boolean) => void; onBack: () => void }) {
  const [lo, hi] = timeline.years;
  const months = useMemo(() => Array.from({ length: Math.min(60, (hi - lo + 1) * 12) }, (_, i) => new Date(lo + Math.floor(i / 12), i % 12, 1)), [lo, hi]);
  const key = (m: Date) => `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`;
  const today = key(new Date());
  const cols = `220px repeat(${months.length}, minmax(0, 1fr))`;
  const orgs = [...new Set(timeline.rows.map((r) => r.org))];

  return (
    <div className="pen-box relative flex h-full w-full flex-col overflow-hidden bg-white">
      <div className="flex items-center gap-2 border-b-2 border-line px-4 py-2">
        <CalendarRange size={16} className="text-grape" />
        <span className="font-logo text-base font-semibold">Timeline</span>
        <span className="truncate text-xs text-muted">{timeline.title}</span>
        <span className="flex-1" />
        <button onClick={onBack} className="flex items-center gap-1 rounded-full border-2 border-pen bg-white px-2.5 py-0.5 text-xs font-semibold hover:bg-grape-soft"><MapIcon size={13} /> Back to map</button>
      </div>
      {!timeline.rows.length && <div className="grid flex-1 place-items-center px-8 text-center text-sm text-muted">No build windows in {lo} to {hi} match.</div>}
      {timeline.rows.length > 0 && (
        <div className="thin-scroll flex-1 overflow-auto">
          <div className="min-w-[640px]">
            <div className="sticky top-0 z-10 grid border-b border-line bg-white text-[10px] font-semibold uppercase tracking-wide text-faint" style={{ gridTemplateColumns: cols }}>
              <div className="px-3 py-1">Project</div>
              {months.map((m) => <div key={key(m)} className={`border-l border-line px-1 py-1 ${m.getMonth() === 0 ? "text-ink" : ""}`}>{MONTHS[m.getMonth()]}{m.getMonth() === 0 ? ` ${String(m.getFullYear()).slice(2)}` : ""}</div>)}
            </div>
            {timeline.rows.map((r) => {
              const s = months.findIndex((m) => key(m) === ym(r.start)), e = months.findIndex((m) => key(m) === ym(r.end));
              const from = s >= 0 ? s : ym(r.start) < key(months[0]) ? 0 : -1, to = e >= 0 ? e : ym(r.end) > key(months[months.length - 1]) ? months.length - 1 : -1;
              const color = colorFor(r.org);
              return (
                <div key={`${r.org}-${r.id}`} className="grid items-stretch border-b border-line hover:bg-soft" style={{ gridTemplateColumns: cols }}>
                  <button onClick={() => onPick(r.id, r.mine)} className="min-w-0 px-3 py-2 text-left">
                    <span className="block truncate text-sm font-semibold">{r.name}</span>
                    <span className="flex items-center gap-1.5 text-xs text-muted"><span className="h-2 w-2 rounded-full" style={{ background: color }} />{r.org_short}{r.kv ? ` · ${r.kv} kV` : ""}</span>
                  </button>
                  {months.map((m, k) => (
                    <div key={key(m)} className="relative border-l border-line" title={`${r.name}: ${r.start} to ${r.end}`}>
                      {key(m) === today && <span className="absolute inset-y-0 left-0 w-0.5 bg-grape" />}
                      {from >= 0 && to >= 0 && k >= from && k <= to && (
                        <button onClick={() => onPick(r.id, r.mine)} aria-label={`Show ${r.name}`}
                          className={`absolute inset-y-2 ${k === from ? "left-1 rounded-l-full" : "left-0"} ${k === to ? "right-1 rounded-r-full" : "right-0"}`}
                          style={{ background: color, opacity: r.mine ? 0.95 : 0.55 }} />
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 border-t-2 border-line px-4 py-1.5 text-[11px] text-muted">
        {orgs.map((o) => <span key={o} className="flex items-center gap-1"><span className="h-2.5 w-4 rounded-full" style={{ background: colorFor(o) }} />{timeline.rows.find((r) => r.org === o)?.org_short}</span>)}
        <span className="flex items-center gap-1"><span className="h-3 w-0.5 bg-grape" />today</span>
        <span>{timeline.rows.length} build window{timeline.rows.length === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}
