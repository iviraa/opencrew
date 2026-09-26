import { CalendarRange, Flag } from "lucide-react";
import { useEffect } from "react";
import { colorFor } from "../data";
import { ItemButtons, useItemActions } from "./PlanItems";
import { StateChip, VERDICT, VerdictChip, accepted, horizonLabel, money, mon, type Verdict } from "./types";
import type { PlanStore } from "./usePlans";

// crewly's plan inside the chat: totals, one card per pair with accept / skip, then timeline and execute
export default function PlanCard({ store, id, horizon, item, onOpenPlan, onOpenGoal }: {
  store: PlanStore; id: number; horizon?: string; item?: string; onOpenPlan: (id: number, item?: string) => void; onOpenGoal: (id: number) => void;
}) {
  const plan = store.plans[id] ?? null;
  const { patch, execute, err } = useItemActions(store, plan, onOpenGoal);
  useEffect(() => { if (!plan) store.load(id).catch(() => {}); }, [id, plan, store]);
  if (!plan) return <div className="rounded-2xl border-2 border-line px-3 py-2 text-xs text-muted"><span className="dots">Loading the plan</span></div>;
  const t = plan.totals, n = accepted(plan).length;
  const shown = item ? plan.items.filter((i) => i.id === item) : plan.items;
  return (
    <div className="pop-in flex flex-col gap-1.5 rounded-2xl border-2 border-pen bg-white p-2">
      <div className="px-1 pt-0.5">
        <div className="flex items-center gap-2 text-xs font-semibold text-faint"><CalendarRange size={13} /> Plan for {horizonLabel(horizon ?? plan.horizon)} · v{plan.version}</div>
        <div className="font-logo text-lg font-semibold text-save">{money(t.savings)}</div>
        <div className="text-xs text-muted">{plan.items.length} pair{plan.items.length === 1 ? "" : "s"} · {money(t.weather_avoided)} of weather cost avoided
          {(Object.keys(VERDICT) as Verdict[]).filter((v) => t.verdicts[v]).map((v) => <span key={v} className="ml-1.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold" style={{ background: VERDICT[v].bg, color: VERDICT[v].color }}>{t.verdicts[v]} {VERDICT[v].label.toLowerCase()}</span>)}
        </div>
        {t.note && <p className="mt-0.5 text-[11px] text-muted">{t.note}</p>}
      </div>
      {err && <p className="rounded-xl bg-warn-soft px-2 py-1 text-xs text-warn">{err}</p>}
      {shown.map((it) => (
        <div key={it.id} className={`rounded-xl border-2 border-line px-2.5 py-1.5 ${it.state === "skipped" ? "opacity-60" : ""}`}>
          <button onClick={() => onOpenPlan(plan.id, it.id)} className="block w-full text-left">
            <div className="flex items-center gap-2"><VerdictChip v={it.verdict} /><span className="text-xs text-faint">#{it.id}</span><span className="flex-1" /><StateChip s={it.state} /></div>
            <div className="mt-0.5 line-clamp-2 text-sm font-semibold leading-snug">{it.ours}</div>
            <div className="flex items-center gap-1.5 text-xs text-muted"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colorFor(it.partner) }} />with {it.partner_short}</div>
            <div className="text-xs text-muted">{mon(it.target_start)} to {mon(it.target_end)} · <span className="font-semibold text-save">{money(it.savings)}</span> · {it.action}</div>
          </button>
          <ItemButtons it={it} onPatch={patch} onOpenGoal={onOpenGoal} small />
        </div>
      ))}
      {!plan.items.length && <p className="px-1 text-xs text-muted">No pairs to plan in this horizon.</p>}
      <div className="flex gap-1.5">
        <button onClick={() => onOpenPlan(plan.id)} className="flex flex-1 items-center justify-center gap-1 rounded-full border-2 border-line px-2.5 py-1 text-xs font-semibold hover:border-pen"><CalendarRange size={13} /> Show timeline</button>
        <button onClick={execute} disabled={store.busy != null || !n} className="flex flex-1 items-center justify-center gap-1 rounded-full bg-grape px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-40"><Flag size={13} /> Execute {n ? `${n} accepted` : "accepted"}</button>
      </div>
    </div>
  );
}
