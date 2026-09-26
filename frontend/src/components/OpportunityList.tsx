import { useState } from "react";
import type { Opportunity, Tier } from "../api";
import Procurement from "./Procurement";
import { FLAG_LABEL, TIER_COLOR, TIER_LABEL, miles, pct, title, usd } from "../format";

type Props = {
  items: Opportunity[];
  shown: Opportunity[];
  crewlyFiltered: boolean;
  onClearCrewly: () => void;
  selectedId: number | null;
  tier: Tier | null;
  onTier: (t: Tier | null) => void;
  onSelect: (id: number) => void;
};

export function TierChip({ tier }: { tier: Tier }) {
  return (
    <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: TIER_COLOR[tier] }}>
      {TIER_LABEL[tier]}
    </span>
  );
}

export default function OpportunityList({ items, shown, crewlyFiltered, onClearCrewly, selectedId, tier, onTier, onSelect }: Props) {
  const [tab, setTab] = useState<"overlaps" | "equipment">("overlaps");
  const tabs = (
    <div className="mb-2 flex gap-4 text-sm">
      {(["overlaps", "equipment"] as const).map((t) => (
        <button key={t} onClick={() => setTab(t)}
          className={`border-b-2 pb-1 font-semibold capitalize ${tab === t ? "border-slate-900 text-slate-900" : "border-transparent text-slate-400"}`}>{t}</button>
      ))}
    </div>
  );
  if (tab === "equipment") {
    return <div className="flex h-full flex-col"><div className="border-b border-slate-200 px-4 pt-3">{tabs}</div><Procurement /></div>;
  }
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 px-4 pb-3 pt-3">
        {tabs}
        <h2 className="text-sm font-semibold text-slate-900">Coordination opportunities</h2>
        <p className="mt-0.5 text-xs text-slate-500">{shown.length} of {items.length} cross-utility pairs within 25 mi, ranked by score</p>
        {crewlyFiltered && (
          <button onClick={onClearCrewly} className="mt-2 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 ring-1 ring-blue-200 hover:bg-blue-100">
            Filtered by Crewly · clear
          </button>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          <button onClick={() => onTier(null)}
            className={`rounded-full px-2.5 py-1 text-xs font-medium ${tier === null ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
            All
          </button>
          {(Object.keys(TIER_LABEL) as Tier[]).map((t) => (
            <button key={t} onClick={() => onTier(t)}
              className={`rounded-full px-2.5 py-1 text-xs font-medium ${tier === t ? "text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
              style={tier === t ? { background: TIER_COLOR[t] } : undefined}>
              {TIER_LABEL[t]} · {items.filter((o) => o.tier === t).length}
            </button>
          ))}
        </div>
      </div>
      <ol className="flex-1 overflow-y-auto">
        {shown.map((o, i) => (
          <li key={o.id}>
            <button onClick={() => onSelect(o.id)}
              className={`w-full border-b border-slate-100 px-4 py-3 text-left hover:bg-slate-50 ${o.id === selectedId ? "bg-blue-50/70" : ""}`}>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 w-5 shrink-0 text-right text-xs font-semibold text-slate-400">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <JobLine name={o.a_name} phase={o.a_phase} color={o.a_color} conf={o.a_conf} />
                  <JobLine name={o.b_name} phase={o.b_phase} color={o.b_color} conf={o.b_conf} />
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600">
                    <TierChip tier={o.tier} />
                    <span>{miles(o.distance_m)}</span>
                    <span>{pct(o.time_overlap)} time overlap</span>
                    <span className="font-medium text-emerald-700">{usd(o.savings_low)}–{usd(o.savings_high)}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-slate-400">
                    <span>score {o.score.toFixed(2)} · {title(o.status)}</span>
                    {o.flags.map((f) => <span key={f} className="rounded bg-orange-50 px-1 text-orange-700 ring-1 ring-orange-200">{FLAG_LABEL[f] ?? f}</span>)}
                  </div>
                </div>
              </div>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function JobLine({ name, phase, color, conf }: { name: string; phase: string | null; color: string; conf: number }) {
  return (
    <div className="flex items-center gap-2 text-[13px] leading-5">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
      <span className="truncate">{name}</span>
      {phase && <span className="shrink-0 rounded bg-slate-100 px-1 text-[10px] text-slate-600">{phase}</span>}
      {conf < 0.7 && <span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">approx</span>}
    </div>
  );
}
