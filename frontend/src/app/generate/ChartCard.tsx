import { BarChart3, Download, FileSpreadsheet } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../data";
import { Card, Drawer, Note, Pill, Row } from "../ui";
import { download, fmt, toCsv, type Chart, type ChartKind } from "./types";

const W = 320, H = 190, PAD = { l: 44, r: 8, t: 8, b: 34 };
const KINDS: ChartKind[] = ["bar", "line", "stacked"];

// a small inline chart: bars, lines or stacked bars, no library; findings reuse it
export function ChartSvg({ chart, onHover, max: shared }: { chart: Chart; onHover: (t: string | null) => void; max?: number }) {
  const n = chart.x.length, series = chart.series;
  const stacked = chart.kind === "stacked";
  const tops = Array.from({ length: n }, (_, i) => stacked ? series.reduce((s, sr) => s + (sr.values[i] ?? 0), 0) : Math.max(...series.map((sr) => sr.values[i] ?? 0)));
  const max = shared ?? Math.max(1, ...tops);  // a pair can share one scale
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (iw * i) / Math.max(n, 1);
  const y = (v: number) => PAD.t + ih - (ih * v) / max;
  const slot = iw / Math.max(n, 1), gap = Math.min(4, slot * 0.2);
  const ticks = [0, 0.5, 1].map((f) => f * max);
  const step = Math.ceil(n / 12);  // label at most a dozen x values
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={chart.title} onMouseLeave={() => onHover(null)}>
      {ticks.map((t) => <g key={t}><line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="#dfe6f2" /><text x={PAD.l - 4} y={y(t) + 3} fontSize="8" textAnchor="end" fill="#8a94b0">{fmt(t, chart.unit)}</text></g>)}
      {chart.kind === "line" ? series.map((sr, k) => (
        <g key={sr.name}>
          <polyline fill="none" stroke={sr.color ?? "#5b2bb5"} strokeWidth="2" points={sr.values.map((v, i) => `${x(i) + slot / 2},${y(v)}`).join(" ")} />
          {sr.values.map((v, i) => <circle key={i} cx={x(i) + slot / 2} cy={y(v)} r="3" fill={sr.color ?? "#5b2bb5"} onMouseEnter={() => onHover(`${chart.x[i]} · ${sr.name}: ${fmt(v, chart.unit)}`)} />)}
          {k === 0 && null}
        </g>
      )) : chart.x.map((lab, i) => {
        let base = 0;
        const bw = stacked ? slot - gap : (slot - gap) / Math.max(series.length, 1);
        return (
          <g key={lab}>
            {series.map((sr, k) => {
              const v = sr.values[i] ?? 0;
              const bx = stacked ? x(i) + gap / 2 : x(i) + gap / 2 + k * bw;
              const y0 = stacked ? y(base + v) : y(v), h = Math.max(0, (stacked ? y(base) : y(0)) - y0);
              if (stacked) base += v;
              return <rect key={sr.name} x={bx} y={y0} width={Math.max(bw, 1)} height={h} rx="1.5" fill={sr.color ?? "#5b2bb5"}
                onMouseEnter={() => onHover(`${lab} · ${sr.name}: ${fmt(v, chart.unit)}`)} />;
            })}
          </g>
        );
      })}
      {chart.x.map((lab, i) => i % step === 0 && (
        <text key={lab + i} x={x(i) + slot / 2} y={H - PAD.b + 12} fontSize="8" textAnchor="end" transform={`rotate(-35 ${x(i) + slot / 2} ${H - PAD.b + 12})`} fill="#5e6a8a">{lab.length > 14 ? lab.slice(0, 13) + "…" : lab}</text>
      ))}
    </svg>
  );
}

export default function ChartCard({ chart: initial }: { chart: Chart }) {
  const [chart, setChart] = useState(initial);
  const [hover, setHover] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const opt = chart.options ?? {};
  const years = Array.isArray(opt.years) ? (opt.years as number[]) : null;

  const rerun = async (options: Record<string, unknown>) => {
    setBusy(true); setErr(null);
    try {
      const r = await api.send<{ chart: Chart }>("/api/app/chart", "POST", { dataset: chart.dataset, options: { ...opt, ...options } });
      setChart(r.chart);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const rows = chart.x.map((lab, i) => ({ x: lab, ...Object.fromEntries(chart.series.map((s) => [s.name, s.values[i]])) }));
  const png = () => {  // draw the svg onto a canvas so the download is a picture
    const svg = box.current?.querySelector("svg");
    if (!svg) return;
    const xml = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    img.onload = () => {
      const c = document.createElement("canvas"); c.width = W * 3; c.height = H * 3;
      const g = c.getContext("2d")!; g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
      c.toBlob((b) => b && download(`${chart.dataset}.png`, b, "image/png"));
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml);
  };

  const peak = chart.series.length === 1 ? (() => { const v = chart.series[0].values; if (!v.length) return null; const i = v.indexOf(Math.max(...v)); return `Peak ${fmt(v[i], chart.unit)} in ${chart.x[i]}`; })() : null;
  const summary = [`${chart.x.length} ${chart.kind === "line" ? "points" : "bars"}`, chart.series.length > 1 ? `${chart.series.length} series` : null, peak].filter(Boolean).join(" · ");

  return (
    <div ref={box}>
      <Card icon={<BarChart3 size={15} />} title={chart.title} sub={hover ?? summary} busy={busy}
        right={<>
          <Pill onClick={png} title="Download as PNG" icon={<Download size={13} />} />
          <Pill onClick={() => download(`${chart.dataset}.csv`, toCsv(["x", ...chart.series.map((s) => s.name)], rows), "text/csv")} title="Download as CSV" icon={<FileSpreadsheet size={13} />} />
        </>}>
        <Drawer title="Chart" summary={chart.source} defaultOpen>
          <ChartSvg chart={chart} onHover={setHover} />
          {chart.series.length > 1 && (
            <Row className="text-[11px] text-muted">
              {chart.series.map((s) => <span key={s.name} className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: s.color ?? "#5b2bb5" }} />{s.name}</span>)}
            </Row>
          )}
          <Row>
            <div className="flex rounded-full bg-soft p-0.5 text-[11px] font-semibold">
              {KINDS.map((k) => <button key={k} onClick={() => rerun({ kind: k })} className={`rounded-full px-2 py-0.5 capitalize ${chart.kind === k ? "bg-white shadow-sm" : "text-muted"}`}>{k}</button>)}
            </div>
            {years && (
              <span className="flex items-center gap-1 text-[11px] text-muted">
                <input type="number" defaultValue={years[0]} aria-label="From year" className="w-14 rounded-full border-2 border-line px-1.5 py-0.5 text-center" onBlur={(e) => rerun({ years: [Number(e.target.value), years[1]] })} />
                to <input type="number" defaultValue={years[1]} aria-label="To year" className="w-14 rounded-full border-2 border-line px-1.5 py-0.5 text-center" onBlur={(e) => rerun({ years: [years[0], Number(e.target.value)] })} />
              </span>
            )}
            {typeof opt.top === "number" && (
              <span className="flex items-center gap-1 text-[11px] text-muted">top <input type="number" defaultValue={opt.top} aria-label="How many" className="w-12 rounded-full border-2 border-line px-1.5 py-0.5 text-center" onBlur={(e) => rerun({ top: Number(e.target.value) })} /></span>
            )}
          </Row>
        </Drawer>
        {err && <Note tone="warn">{err}</Note>}
      </Card>
    </div>
  );
}
