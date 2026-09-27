import { Columns2, Download, Maximize2, Ruler, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Card, Pill, Row } from "../ui";
import { ChartSvg } from "./ChartCard";
import { chartTop, download, fmt, toCsv, type Chart } from "./types";

// the busiest point of a chart, in words: "Peak 3.8 days in Jul"
function peak(c: Chart) {
  const tot = c.x.map((_, i) => c.series.reduce((s, sr) => s + (c.kind === "stacked" ? sr.values[i] ?? 0 : 0), 0) || Math.max(...c.series.map((sr) => sr.values[i] ?? 0)));
  if (!tot.length) return null;
  const i = tot.indexOf(Math.max(...tot));
  return `Peak ${fmt(tot[i], c.unit)}${c.unit && !["USD", "%"].includes(c.unit) ? ` ${c.unit}` : ""} in ${c.x[i]}`;
}

function Legend({ c, big }: { c: Chart; big?: boolean }) {
  if (c.series.length < 2) return null;
  return (
    <div className={`flex flex-wrap gap-x-2 gap-y-0.5 ${big ? "text-xs" : "text-[10px]"} text-muted`}>
      {c.series.map((s) => <span key={s.name} className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: s.color ?? "#5b2bb5" }} />{s.name}</span>)}
    </div>
  );
}

function Pane({ c, max, big, onHover }: { c: Chart; max?: number; big?: boolean; onHover: (t: string | null) => void }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1 rounded-xl border-2 border-line bg-white ${big ? "p-4" : "p-1.5"}`}>
      <div className={`${big ? "text-base" : "line-clamp-2 text-[11px]"} font-semibold leading-snug`}>{c.title}</div>
      <div className={`${big ? "text-xs" : "text-[10px]"} text-muted`}>{peak(c)}</div>
      <ChartSvg chart={c} max={max} onHover={onHover} />
      <Legend c={c} big={big} />
      {big && <div className="text-[11px] text-faint">{c.source}</div>}
    </div>
  );
}

// two charts next to each other in the chat, with one scale when the units match and a large view for a closer look
export default function ChartPair({ a, b }: { a: Chart; b: Chart }) {
  const [hover, setHover] = useState<string | null>(null);
  const [same, setSame] = useState(a.unit === b.unit);
  const [big, setBig] = useState(false);
  const canShare = a.unit === b.unit;
  const max = same && canShare ? Math.max(chartTop(a), chartTop(b)) : undefined;

  useEffect(() => {
    if (!big) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setBig(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [big]);

  const csv = () => {
    const cols = ["chart", "x", ...Array.from(new Set([...a.series, ...b.series].map((s) => s.name)))];
    const rows = [a, b].flatMap((c) => c.x.map((x, i) => ({ chart: c.title, x, ...Object.fromEntries(c.series.map((s) => [s.name, s.values[i]])) })));
    download("side-by-side.csv", toCsv(cols, rows), "text/csv");
  };

  return (
    <>
      <Card icon={<Columns2 size={15} />} title="Side by side" sub={hover ?? (max ? "Both charts share one scale" : "Each chart has its own scale")}
        right={<>
          {canShare && <Pill onClick={() => setSame(!same)} pressed={same} title={same ? "Use separate scales" : "Use one scale for both"} icon={<Ruler size={13} />} />}
          <Pill onClick={csv} title="Download both as CSV" icon={<Download size={13} />} />
          <Pill onClick={() => setBig(true)} title="Open larger" icon={<Maximize2 size={13} />} />
        </>}>
        <div className="grid grid-cols-2 gap-1.5">
          <Pane c={a} max={max} onHover={setHover} />
          <Pane c={b} max={max} onHover={setHover} />
        </div>
      </Card>
      {big && createPortal(
        <div className="fixed inset-0 z-[100] grid place-items-center bg-black/40 p-6" onClick={() => setBig(false)} role="dialog" aria-modal="true" aria-label="Charts side by side">
          <div className="pop-in flex max-h-[92vh] w-[min(1100px,94vw)] flex-col gap-3 overflow-auto rounded-3xl border-2 border-pen bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <Row>
              <Columns2 size={18} className="text-grape" />
              <span className="flex-1 font-logo text-xl font-semibold">Side by side</span>
              <span className="text-xs text-muted">{hover ?? (max ? "One scale for both" : "Separate scales")}</span>
              {canShare && <Pill onClick={() => setSame(!same)} pressed={same} icon={<Ruler size={13} />}>{same ? "One scale" : "Own scales"}</Pill>}
              <button onClick={() => setBig(false)} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-full border-2 border-pen hover:bg-grape-soft"><X size={16} strokeWidth={2.5} /></button>
            </Row>
            <div className="grid grid-cols-2 gap-4">
              <Pane c={a} max={max} big onHover={setHover} />
              <Pane c={b} max={max} big onHover={setHover} />
            </div>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
