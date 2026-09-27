import { CalendarRange, Flag } from "lucide-react";
import { useEffect } from "react";
import { colorFor } from "../data";
import { Card, Chip, Drawer, Lead, Note, Pill, RefLink, Row, StatRow, plural } from "../ui";
import { ItemButtons, useItemActions } from "./PlanItems";
import { StateChip, VERDICT, VerdictChip, accepted, horizonLabel, money, mon, type Item, type Plan, type Verdict } from "./types";
import type { PlanStore } from "./usePlans";

const SHOWN = 3;

function PlanItem({ it, plan, onOpenPlan, onOpenGoal, onOpenOverlap, patch }: {
  it: Item; plan: Plan; onOpenPlan: (id: number, item?: string) => void; onOpenGoal: (id: number) => void; onOpenOverlap?: (id: number) => void; patch: ReturnType<typeof useItemActions>["patch"];
}) {
  return (
    <div className={`rounded-xl border-2 border-line px-2.5 py-1.5 ${it.state === "skipped" ? "opacity-60" : ""}`}>
      <div className="flex items-center gap-2"><VerdictChip v={it.verdict} /><RefLink id={it.opportunity_id} onOpen={onOpenOverlap} /><span className="flex-1" /><StateChip s={it.state} /></div>
      <button onClick={() => onOpenPlan(plan.id, it.id)} className="mt-0.5 block w-full text-left">
        <div className="line-clamp-2 text-sm font-semibold leading-snug">{it.ours}</div>
        <div className="flex items-center gap-1.5 text-xs text-muted"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: colorFor(it.partner) }} />with {it.partner_short}</div>
        <div className="text-xs text-muted">{mon(it.target_start)} to {mon(it.target_end)} · <span className="font-semibold text-save">{money(it.savings)}</span> · {it.action}</div>
      </button>
      <ItemButtons it={it} onPatch={patch} onOpenGoal={onOpenGoal} small />
    </div>
  );
}

// crewly's plan inside the chat: the totals and the first pairs, the rest in a drawer, then timeline and execute
const signed = (r: { low: number; high: number }) => {  // "+$12k to +$40k", "no change"
  if (Math.abs(r.low) < 50 && Math.abs(r.high) < 50) return "no change";
  const f = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${money({ low: Math.abs(v), high: Math.abs(v) }).split(" to ")[0]}`;
  return Math.round(r.low / 100) === Math.round(r.high / 100) ? f(r.low) : `${f(r.low)} to ${f(r.high)}`;
};

export default function PlanCard({ store, id, horizon, item, onOpenPlan, onOpenGoal, onOpenOverlap }: {
  store: PlanStore; id: number; horizon?: string; item?: string; onOpenPlan: (id: number, item?: string) => void; onOpenGoal: (id: number) => void; onOpenOverlap?: (id: number) => void;
}) {
  const plan = store.plans[id] ?? null;
  const { patch, execute, err } = useItemActions(store, plan, onOpenGoal);
  useEffect(() => { if (!plan) store.load(id).catch(() => {}); }, [id, plan, store]);
  if (!plan) return <div className="rounded-2xl border-2 border-line px-3 py-2 text-xs text-muted"><span className="dots">Loading the plan</span></div>;
  const t = plan.totals, n = accepted(plan).length;
  const items = item ? plan.items.filter((i) => i.id === item) : plan.items;
  const head = items.slice(0, SHOWN), rest = items.slice(SHOWN);
  const verdicts = (Object.keys(VERDICT) as Verdict[]).filter((v) => t.verdicts[v]);
  const common = { plan, onOpenPlan, onOpenGoal, onOpenOverlap, patch };
  return (
    <Card icon={<CalendarRange size={15} />} title={`Plan for ${horizonLabel(horizon ?? plan.horizon)}`}
      sub={<Row><Chip tone="info">v{plan.version}</Chip><span>{plural(plan.items.length, "pair")}{t.period ? ` · ${mon(t.period[0])} to ${mon(t.period[1])}` : ""}</span></Row>}>
      <Lead>
        {plan.items.length
          ? `${plural(plan.items.length, "pair")} worth pursuing, with expected savings of ${money(t.savings)}${t.weather_avoided.high > 0 ? ` and ${money(t.weather_avoided)} of weather cost avoided by the chosen months` : ""}.`
          : "No pairs fit this horizon. Try a longer one."}
      </Lead>
      {plan.items.length > 0 && <StatRow items={[
        { label: "Expected savings", value: money(t.savings), tone: "good" },
        { label: "Weather avoided", value: money(t.weather_avoided), tone: t.weather_avoided.high > 0 ? "good" : "flat" },
        { label: "Accepted", value: `${n} of ${plan.items.length}`, note: t.conflicts > 0 ? plural(t.conflicts, "conflict") : undefined, tone: n ? "info" : "flat" },
      ]} />}
      {t.edits && t.edits.length > 0 && t.built && (
        <Drawer title={`Changed since built · ${plural(t.edits.length, "edit")}`}
          summary={`Weather cost ${money(t.built.weather_cost)} → ${money(t.weather_cost ?? t.built.weather_cost)} · savings ${money(t.built.savings)} → ${money(t.savings)}`}>
          <ol className="flex flex-col gap-1">
            {t.edits.map((e, i) => (
              <li key={i} className="rounded-xl bg-soft px-2.5 py-1.5 text-xs leading-snug">
                <span className="block">{e.summary}</span>
                <span className="text-muted">Savings {signed(e.effect.savings)} · weather cost {signed(e.effect.weather_cost)}</span>
              </li>
            ))}
          </ol>
        </Drawer>
      )}
      {verdicts.length > 0 && <Row>{verdicts.map((v) => <Chip key={v} style={{ background: VERDICT[v].bg, color: VERDICT[v].color }}>{t.verdicts[v]} {VERDICT[v].label.toLowerCase()}</Chip>)}</Row>}
      {t.note && <Note>{t.note}</Note>}
      {err && <Note tone="warn">{err}</Note>}
      {head.map((it) => <PlanItem key={it.id} it={it} {...common} />)}
      {rest.length > 0 && (
        <Drawer title={`${rest.length} more pair${rest.length === 1 ? "" : "s"}`} summary={rest.map((i) => `#${i.opportunity_id}`).join(", ")}>
          {rest.map((it) => <PlanItem key={it.id} it={it} {...common} />)}
        </Drawer>
      )}
      {plan.items.length > 0 && (
        <Row>
          <Pill grow onClick={() => onOpenPlan(plan.id)} icon={<CalendarRange size={13} />}>Timeline</Pill>
          <Pill grow primary onClick={execute} disabled={store.busy != null || !n} icon={<Flag size={13} />}>Execute {n ? `${n} accepted` : "accepted"}</Pill>
        </Row>
      )}
    </Card>
  );
}
