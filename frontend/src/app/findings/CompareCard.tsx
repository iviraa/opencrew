import { GitCompare } from "lucide-react";
import { direction, show, signed, unitOf, type Comparison, type Finding } from "./types";

const TONE = { good: "text-save", bad: "text-warn", flat: "text-muted" };
const name = (x: Finding | number) => (typeof x === "number" ? `#${x}` : x.title);

// two findings side by side, metric by metric
export default function CompareCard({ comparison }: { comparison: Comparison }) {
  const { a, b, deltas } = comparison;
  return (
    <div className="pop-in flex flex-col gap-1.5 rounded-2xl border-2 border-pen bg-white p-2">
      <div className="flex items-center gap-2 px-1 text-sm font-semibold leading-snug"><GitCompare size={14} className="shrink-0 text-grape" /> {comparison.title ?? `${name(a)} vs ${name(b)}`}</div>
      <div className="rounded-xl border-2 border-line">
        <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-faint"><span>Metric</span><span className="max-w-24 truncate">{name(a)}</span><span className="max-w-24 truncate">{name(b)}</span><span className="text-right">B minus A</span></div>
        {deltas.map((d) => {
          const u = unitOf(d.metric, d.unit);
          return (
            <div key={d.metric} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 border-t border-line px-2 py-1 text-[11px]">
              <span className="truncate text-muted">{d.label}</span><span>{show(d.base, u)}</span><span className="font-semibold">{show(d.scenario, u)}</span>
              <span className={`text-right font-semibold ${TONE[direction(d.metric, d.delta)]}`}>{typeof d.delta === "number" && d.delta === 0 ? "same" : signed(d.delta, u)}</span>
            </div>
          );
        })}
        {!deltas.length && <p className="px-2 py-2 text-[11px] text-muted">These two share no metrics to compare.</p>}
      </div>
    </div>
  );
}
