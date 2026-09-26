import { CalendarRange, Car, CloudLightning, Ruler, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { Opportunity, Tier } from "../api";
import { FLAG_LABEL, TIER_COLOR, TIER_HINT, TIER_LABEL, TIER_SOFT, TIER_INK, miles, pct, title, tooFar, usd } from "../format";
import Procurement from "./Procurement";
import { Empty, PairBubble, TierPill } from "./ui";

type Props = {
  items: Opportunity[];
  shown: Opportunity[];
  crewlyFiltered: boolean;
  onClearCrewly: () => void;
  selectedId: number | null;
  tier: Tier | null;
  onTier: (t: Tier | null) => void;
  onSelect: (id: number) => void;
  loading: boolean;
  emptyText: string;
  roadOnly: boolean;
  onRoadOnly: (v: boolean) => void;
  tabRequest?: { tab: string; at: number } | null;
  planPanel?: ReactNode;
  onTab?: (tab: string) => void;
};

type Tab = "overlaps" | "plan" | "equipment";
const TABS: { id: Tab; label: string }[] = [{ id: "overlaps", label: "Team-ups" }, { id: "plan", label: "Joint plan" }, { id: "equipment", label: "Equipment" }];

export function TierChip({ tier }: { tier: Tier }) {
  return <TierPill tier={tier} size="sm" />;  // kept for older imports
}

export default function OpportunityList({ items, shown, crewlyFiltered, onClearCrewly, selectedId, tier, onTier, onSelect, loading, emptyText, roadOnly, onRoadOnly, tabRequest, planPanel, onTab }: Props) {
  const [tab, setTabState] = useState<Tab>("overlaps");
  const setTab = (t: Tab) => { setTabState(t); onTab?.(t); };
  useEffect(() => { if (tabRequest?.tab === "overlaps" || tabRequest?.tab === "equipment" || tabRequest?.tab === "plan") setTab(tabRequest.tab); }, [tabRequest]);  // crewly can switch tabs

  const tabs = (
    <div role="tablist" className="flex rounded-full bg-soft p-1 ring-1 ring-line">
      {TABS.map((t) => (
        <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
          className={`flex-1 rounded-full px-3 py-1.5 text-[14px] font-semibold transition ${tab === t.id ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}>{t.label}</button>
      ))}
    </div>
  );
  if (tab !== "overlaps") {
    return <div className="flex h-full flex-col"><div className="px-5 pb-3 pt-4">{tabs}</div><div className="min-h-0 flex-1 overflow-y-auto thin-scroll">{tab === "plan" ? planPanel : <Procurement />}</div></div>;
  }

  const low = shown.reduce((s, o) => s + o.savings_low, 0);
  const high = shown.reduce((s, o) => s + o.savings_high, 0);
  const nearby = items.filter((o) => !tooFar(o.drive_min)).length;

  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-3 pt-4">
        {tabs}
        <h2 className="mt-4 text-[22px] font-semibold leading-tight">{loading ? "Finding team-ups…" : `${shown.length} places to team up`}</h2>
        {!loading && shown.length > 0 && (
          <p className="mt-1 text-[14px] text-muted">Together they could save <span className="font-semibold text-save">{usd(low)} to {usd(high)}</span></p>
        )}
        {crewlyFiltered && (
          <button onClick={onClearCrewly} className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-desc-soft px-3 py-1 text-[13px] font-semibold text-desc">
            Showing what Crewly found <X size={14} />
          </button>
        )}
        <div className="-mx-1 mt-4 flex flex-wrap gap-2 px-1">
          <FilterChip active={tier === null} onClick={() => onTier(null)} color="#1b2447">All {items.length}</FilterChip>
          {(Object.keys(TIER_LABEL) as Tier[]).map((t) => {
            const n = items.filter((o) => o.tier === t).length;
            return n ? <FilterChip key={t} active={tier === t} onClick={() => onTier(tier === t ? null : t)} color={TIER_COLOR[t]} soft={TIER_SOFT[t]} ink={TIER_INK[t]} title={TIER_HINT[t]}>{TIER_LABEL[t]} {n}</FilterChip> : null;
          })}
          <FilterChip active={roadOnly} onClick={() => onRoadOnly(!roadOnly)} color="#12a36b" soft="#dff6ec" ink="#0b7a4f"
            title="Crews and yards can only be shared when the sites are within a 45 minute drive"><Car size={14} /> Easy drive {nearby}</FilterChip>
        </div>
      </div>
      <ol className="thin-scroll min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-4">
        {!loading && shown.length === 0 && <li><Empty title="Nothing here yet">{emptyText}</Empty></li>}
        {!loading && shown.map((o, i) => <Row key={o.id} o={o} rank={i + 1} selected={o.id === selectedId} onSelect={onSelect} />)}
      </ol>
    </div>
  );
}

function FilterChip({ active, onClick, color, soft, ink, title, children }: { active: boolean; onClick: () => void; color: string; soft?: string; ink?: string; title?: string; children: ReactNode }) {
  return (
    <button onClick={onClick} title={title} aria-pressed={active}
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-semibold transition"
      style={active ? { background: color, color: "#fff" } : { background: soft ?? "#f5f8fd", color: ink ?? "#5e6a8a" }}>
      {!active && soft && <span className="h-2 w-2 rounded-full" style={{ background: color }} />}
      {children}
    </button>
  );
}

function Row({ o, rank, selected, onSelect }: { o: Opportunity; rank: number; selected: boolean; onSelect: (id: number) => void }) {
  const far = tooFar(o.drive_min);
  const storm = o.flags.includes("hurricane_season_high_risk");
  const a = o.a_phase ? `${o.a_name} (${o.a_phase})` : o.a_name;
  const b = o.b_phase ? `${o.b_name} (${o.b_phase})` : o.b_name;
  return (
    <li>
      <button onClick={() => onSelect(o.id)} aria-current={selected}
        className={`group relative w-full rounded-2xl px-4 py-3.5 text-left transition ${selected ? "bg-desc-soft/70 ring-2 ring-desc/30" : "hover:bg-soft"}`}>
        <div className="flex items-start gap-3">
          <span className="display mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-[13px] font-semibold"
            style={far ? { background: "#eef1f7", color: "#5e6a8a" } : { background: TIER_SOFT[o.tier], color: TIER_INK[o.tier] }}>{rank}</span>
          <div className="min-w-0 flex-1">
            <PairBubble a={a} b={b} />
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[13px] text-muted">
              <TierPill tier={o.tier} far={far} size="sm" />
              <span className="inline-flex items-center gap-1"><Ruler size={14} />{miles(o.distance_m)}</span>
              {o.drive_min != null && <span className={`inline-flex items-center gap-1 ${far ? "font-semibold text-warn" : ""}`}><Car size={14} />{Math.round(o.drive_min)} min</span>}
              <span className="inline-flex items-center gap-1" title="How much the two work windows overlap"><CalendarRange size={14} />{pct(o.time_overlap)} same time</span>
              {storm && <span className="inline-flex items-center text-warn" title={FLAG_LABEL.hurricane_season_high_risk}><CloudLightning size={15} /></span>}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className={`display text-[16px] font-semibold ${o.savings_high > 0 ? "text-save" : "text-faint"}`}>{o.savings_high > 0 ? usd(o.savings_high) : "$0"}</div>
            <div className="text-[12px] text-faint">{o.savings_high > 0 ? `from ${usd(o.savings_low)}` : far ? "too far" : "not same time"}</div>
            {o.status !== "not_contacted" && <div className="mt-1 text-[12px] font-semibold text-desc">{title(o.status)}</div>}
          </div>
        </div>
      </button>
    </li>
  );
}
