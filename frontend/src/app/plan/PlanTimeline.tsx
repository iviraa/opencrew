import { AlertTriangle, Map as MapIcon, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { colorFor } from "../data";
import { MONTHS, VERDICT, axis, key, mon, type Plan, type Verdict } from "./types";

// the month grid: one lane per pair, a bar for the proposed months colored by verdict, hazard shading underneath
export default function PlanTimeline({ plan, open, busy, onOpen, onBack, onRebuild, ghosts = {} }: {
  plan: Plan | null; open: string | null; busy: boolean; onOpen: (itemId: string) => void; onBack: () => void; onRebuild: () => void;
  ghosts?: Record<string, number>;  // an experiment's shifted windows, months per pair id, drawn as ghost bars
}) {
  const items = plan?.items ?? [];
  const months = useMemo(() => (plan ? axis(plan) : []), [plan]);
  const today = new Date();
  const todayIdx = months.findIndex((m) => m.getFullYear() === today.getFullYear() && m.getMonth() === today.getMonth());
  const cols = `220px repeat(${months.length}, minmax(0, 1fr))`;

  return (
    <div className="pen-box relative flex h-full w-full flex-col overflow-hidden bg-white">
      <div className="flex items-center gap-2 border-b-2 border-line px-4 py-2">
        <span className="font-logo text-base font-semibold">{plan ? `Plan v${plan.version}` : "Plan"}</span>
        <span className="text-xs text-muted">{plan?.totals.period ? `${mon(plan.totals.period[0])} to ${mon(plan.totals.period[1])}` : "whole build windows"}</span>
        <span className="flex-1" />
        <button onClick={onRebuild} disabled={busy} className="flex items-center gap-1 rounded-full border-2 border-line px-2.5 py-0.5 text-xs font-semibold hover:border-pen disabled:opacity-50"><RefreshCw size={13} /> Rebuild</button>
        <button onClick={onBack} className="flex items-center gap-1 rounded-full border-2 border-pen bg-white px-2.5 py-0.5 text-xs font-semibold hover:bg-grape-soft"><MapIcon size={13} /> Back to map</button>
      </div>
      {!plan && <div className="grid flex-1 place-items-center text-muted"><span className="dots">{busy ? "Planning" : "Loading"}</span></div>}
      {plan && !items.length && <div className="grid flex-1 place-items-center px-8 text-center text-sm text-muted">No pairs to plan for this horizon. {plan.totals.note || "Try a longer horizon."}</div>}
      {plan && items.length > 0 && (
        <div className="thin-scroll flex-1 overflow-auto">
          <div className="min-w-[640px]">
            <div className="sticky top-0 z-10 grid border-b border-line bg-white text-[10px] font-semibold uppercase tracking-wide text-faint" style={{ gridTemplateColumns: cols }}>
              <div className="px-3 py-1">Pair</div>
              {months.map((m) => <div key={key(m)} className={`border-l border-line px-1 py-1 ${m.getMonth() === 0 ? "text-ink" : ""}`}>{MONTHS[m.getMonth()]}{m.getMonth() === 0 || m === months[0] ? ` ${String(m.getFullYear()).slice(2)}` : ""}</div>)}
            </div>
            {items.map((it) => {
              const s = months.findIndex((m) => key(m) === it.target_start.slice(0, 7)), e = months.findIndex((m) => key(m) === it.target_end.slice(0, 7));
              const from = s >= 0 ? s : 0, to = e >= 0 ? e : months.length - 1;
              const dim = it.state === "skipped";
              const shift = ghosts[String(it.id)] ?? 0, gFrom = from + shift, gTo = to + shift;
              return (
                <div key={it.id} className={`grid items-stretch border-b border-line hover:bg-soft ${open === it.id ? "bg-grape-soft/60" : ""}`} style={{ gridTemplateColumns: cols }}>
                  <button onClick={() => onOpen(it.id)} className="min-w-0 px-3 py-2 text-left">
                    <span className={`block truncate text-sm font-semibold ${dim ? "text-faint line-through" : ""}`}>{it.ours}</span>
                    <span className="flex items-center gap-1.5 text-xs text-muted"><span className="h-2 w-2 rounded-full" style={{ background: colorFor(it.partner) }} />with {it.partner_short}{it.conflicts.length > 0 && <AlertTriangle size={12} className="text-warn" />}</span>
                  </button>
                  {months.map((m, k) => {
                    const days = it.hazard_strip[String(m.getMonth() + 1)] ?? 0;
                    const inBar = k >= from && k <= to;
                    return (
                      <div key={key(m)} className="relative border-l border-line" style={{ background: `rgba(17,16,20,${Math.min(days / 6, 0.22)})` }}
                        title={`${MONTHS[m.getMonth()]}: about ${days} weather-affected days`}>
                        {k === todayIdx && <span className="absolute inset-y-0 left-0 w-0.5 bg-grape" />}
                        {shift !== 0 && k >= gFrom && k <= gTo && (
                          <span aria-hidden className={`absolute inset-y-3 border-2 border-dashed border-grape ${k === gFrom ? "left-1 rounded-l-full" : "left-0 border-l-0"} ${k === gTo ? "right-1 rounded-r-full" : "right-0 border-r-0"}`} style={{ background: "rgba(91,43,181,0.12)" }} />
                        )}
                        {inBar && (
                          <button onClick={() => onOpen(it.id)} aria-label={`Open #${it.id}`}
                            className={`absolute inset-y-2 ${k === from ? "left-1 rounded-l-full" : "left-0"} ${k === to ? "right-1 rounded-r-full" : "right-0"}`}
                            style={{ background: VERDICT[it.verdict].color, opacity: dim ? 0.3 : it.state === "accepted" ? 1 : 0.75 }} />
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 border-t-2 border-line px-4 py-1.5 text-[11px] text-muted">
        {(Object.keys(VERDICT) as Verdict[]).map((v) => <span key={v} className="flex items-center gap-1"><span className="h-2.5 w-4 rounded-full" style={{ background: VERDICT[v].color }} />{VERDICT[v].label}</span>)}
        <span className="flex items-center gap-1"><span className="h-2.5 w-4 rounded-sm bg-[rgba(17,16,20,0.2)]" />weather-affected days</span>
        <span className="flex items-center gap-1"><AlertTriangle size={11} className="text-warn" />same project, same months</span>
        {Object.keys(ghosts).length > 0 && <span className="flex items-center gap-1"><span className="h-2.5 w-4 rounded-full border-2 border-dashed border-grape" />shifted in the experiment</span>}
      </div>
    </div>
  );
}
