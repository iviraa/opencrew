import { GitCompare } from "lucide-react";
import { Card, Drawer, Lead, StatRow, signedPct, signedUnit, withUnit } from "../ui";
import { compareSentence, movers } from "./prose";
import { direction, show, signed, unitOf, type Comparison, type Finding } from "./types";

const TONE = { good: "text-save", bad: "text-warn", flat: "text-muted" };
const name = (x: Finding | number) => (typeof x === "number" ? `#${x}` : x.title);

// two findings side by side: the sentence, the biggest differences, then every metric in a drawer
export default function CompareCard({ comparison }: { comparison: Comparison }) {
  const { a, b, deltas } = comparison;
  const top = movers(deltas).slice(0, 3);
  return (
    <Card icon={<GitCompare size={15} />} title={comparison.title ?? `${name(a)} vs ${name(b)}`} sub="Comparison of two saved findings">
      <Lead>{compareSentence(comparison)}</Lead>
      <StatRow items={top.map((d) => { const u = unitOf(d.metric, d.unit); return {
        label: d.label, value: withUnit(d.scenario as number, u), tone: direction(d.metric, d.delta),
        note: `${signedUnit(Number(d.delta), u)}${d.pct != null && d.pct !== 0 ? ` · ${signedPct(d.pct)}` : ""}`,
      }; })} />
      <Drawer title="Every metric" summary={`${deltas.length} compared`} defaultOpen={deltas.length <= 4}>
        <div className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 text-[10px] font-semibold uppercase tracking-wide text-faint"><span>Metric</span><span className="max-w-20 truncate">{name(a)}</span><span className="max-w-20 truncate">{name(b)}</span><span className="text-right">B − A</span></div>
        {deltas.map((d) => {
          const u = unitOf(d.metric, d.unit);
          return (
            <div key={d.metric} className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-2 border-t border-line pt-1 text-[11px] tabular-nums">
              <span className="truncate text-muted">{d.label}</span><span>{show(d.base, u)}</span><span className="font-semibold">{show(d.scenario, u)}</span>
              <span className={`text-right font-semibold ${TONE[direction(d.metric, d.delta)]}`}>{typeof d.delta === "number" && d.delta === 0 ? "same" : signed(d.delta, u)}</span>
            </div>
          );
        })}
        {!deltas.length && <p className="text-[11px] text-muted">These two share no metrics to compare.</p>}
      </Drawer>
    </Card>
  );
}
