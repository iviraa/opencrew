import { AlertTriangle, Check, ExternalLink, Flag, SkipForward } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type Me } from "../data";
import { say } from "../mascot";
import { PanelHeader } from "../panels";
import { HORIZONS, MonthPicker, StateChip, VERDICT, VerdictChip, accepted, money, mon, pending, type Explain, type Horizon, type Item, type ItemPatch, type Plan, type Verdict } from "./types";
import type { PlanStore } from "./usePlans";

// accept, skip or move an item; shared by the chat card and the panel
export function useItemActions(store: PlanStore, plan: Plan | null, onOpenGoal: (id: number) => void) {
  const [err, setErr] = useState<string | null>(null);
  const patch = async (id: string, body: ItemPatch) => {
    if (!plan) return;
    try {
      await store.patch(plan.id, id, body);
      if (body.state === "accepted") say(`Accepted #${id}. Execute the plan when you're ready.`, "nod");
      if (body.state === "skipped") say(`Skipped #${id}.`, "nod");
    } catch (e) { setErr(String((e as Error).message ?? e)); }
  };
  const execute = async () => {
    if (!plan) return;
    try {
      const r = await store.execute(plan.id);
      say(`Drafted ${r.drafted} request${r.drafted === 1 ? "" : "s"}. Review and send them from the goal panel.`, "happy");
      onOpenGoal(r.task_id);
    } catch (e) { setErr(String((e as Error).message ?? e)); say("Nothing to execute yet.", "sad"); }
  };
  return { patch, execute, err };
}

export function ItemButtons({ it, onPatch, onOpenGoal, small }: { it: Item; onPatch: (id: string, body: ItemPatch) => void; onOpenGoal: (id: number) => void; small?: boolean }) {
  const [pick, setPick] = useState(false);
  if (it.goal_id) return <button onClick={() => onOpenGoal(it.goal_id!)} className="mt-1 flex items-center gap-1 text-xs font-semibold text-grape hover:underline"><Flag size={12} /> In goal {it.goal_id}</button>;
  if (it.state === "skipped") return <button onClick={() => onPatch(it.id, { state: "proposed" })} className="mt-1 text-xs font-semibold text-grape underline">Bring back</button>;
  if (!pending(it)) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      {it.state !== "accepted" && <button onClick={() => onPatch(it.id, { state: "accepted" })} className="flex items-center gap-1 rounded-full bg-save px-2.5 py-0.5 text-xs font-semibold text-white"><Check size={12} /> Accept</button>}
      <button onClick={() => onPatch(it.id, { state: "skipped" })} className="flex items-center gap-1 rounded-full border-2 border-line px-2.5 py-0.5 text-xs font-semibold hover:border-pen"><SkipForward size={12} /> Skip</button>
      {small && !pick ? <button onClick={() => setPick(true)} className="text-xs font-semibold text-grape underline">Change months</button>
        : <MonthPicker item={it} onChange={(s, e) => onPatch(it.id, { target_start: s, target_end: e })} />}
    </div>
  );
}

export function PlanSummary({ plan }: { plan: Plan }) {
  const t = plan.totals;
  return (
    <div className="rounded-2xl bg-save-soft/70 px-3 py-2.5">
      <div className="text-xs font-semibold uppercase tracking-wide text-faint">Expected savings</div>
      <div className="font-logo text-2xl font-semibold text-save">{money(t.savings)}</div>
      <div className="text-xs text-muted">plus {money(t.weather_avoided)} of weather cost avoided by the chosen months</div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {(Object.keys(VERDICT) as Verdict[]).filter((v) => t.verdicts[v]).map((v) => <span key={v} className="rounded-full px-2 py-0.5 text-xs font-semibold" style={{ background: VERDICT[v].bg, color: VERDICT[v].color }}>{t.verdicts[v]} {VERDICT[v].label.toLowerCase()}</span>)}
        {t.conflicts > 0 && <span className="rounded-full bg-warn-soft px-2 py-0.5 text-xs font-semibold text-warn">{t.conflicts} conflict{t.conflicts === 1 ? "" : "s"}</span>}
        {t.passed > 0 && <span className="rounded-full bg-soft px-2 py-0.5 text-xs font-semibold text-muted">{t.passed} filed window{t.passed === 1 ? "" : "s"} already passed</span>}
      </div>
      {t.note && <p className="mt-1.5 text-xs text-muted">{t.note}</p>}
    </div>
  );
}

function ExecuteButton({ plan, busy, onExecute }: { plan: Plan; busy: boolean; onExecute: () => void }) {
  const n = accepted(plan).length;
  return (
    <button onClick={onExecute} disabled={busy || !n} className="pen-btn mt-2 flex w-full items-center justify-center gap-2 bg-grape px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
      <Flag size={15} /> Execute {n ? `${n} accepted` : "accepted items"}
    </button>
  );
}

function Detail({ plan, item, onBack, onPatch, onOpenOverlap, onOpenGoal }: {
  plan: Plan; item: Item; onBack: () => void; onPatch: (id: string, body: ItemPatch) => void; onOpenOverlap: (id: number) => void; onOpenGoal: (id: number) => void;
}) {
  const [explain, setExplain] = useState<Explain | null>(null);
  const [note, setNote] = useState(item.note);
  useEffect(() => { setExplain(null); api.get<Explain>(`/api/app/plan/${plan.id}/explain/${item.id}`).then(setExplain).catch(() => {}); }, [plan.id, item.id]);
  useEffect(() => { setNote(item.note); }, [item.id, item.note]);
  const w = item.weather;
  return (
    <>
      <PanelHeader title={`#${item.id} ${item.partner_short}`} sub={<span className="flex items-center gap-2"><VerdictChip v={item.verdict} /><StateChip s={item.state} /></span>} onBack={onBack} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
        <div className="rounded-2xl border-2 border-line px-3 py-2">
          <div className="text-sm font-semibold leading-snug">{item.ours}</div>
          <div className="text-xs text-muted">with {item.theirs} ({item.partner_name})</div>
          <button onClick={() => onOpenOverlap(item.opportunity_id)} className="mt-1 flex items-center gap-1 text-xs font-semibold text-grape hover:underline"><ExternalLink size={12} /> Open overlap</button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Savings</div><div className="font-logo text-base font-semibold text-save">{money(item.savings)}</div></div>
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Feasibility</div><div className="font-logo text-base font-semibold">{Math.round(item.feasibility * 100)}%</div><div className="text-[11px] text-muted">{item.feasibility_source}</div></div>
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Windows overlap</div><div className="font-logo text-base font-semibold">{item.window.overlap_pct}%</div></div>
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Action</div><div className="text-sm font-semibold capitalize">{item.action}</div><div className="text-[11px] text-muted">{item.action_reason}</div></div>
        </div>
        <section className="rounded-2xl bg-grape-soft/50 px-3 py-2.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-faint">Why these months</div>
          <div className="font-logo text-lg font-semibold">{mon(item.target_start)} to {mon(item.target_end)}</div>
          <p className="text-xs text-muted">
            About {money(w.target)} of weather cost, against {money(w.naive)} starting {mon(w.naive_window[0])}: {money(w.avoided)} avoided.
            {" "}{w.days.low === w.days.high ? w.days.high : `${w.days.low} to ${w.days.high}`} affected days expected.
          </p>
          <div className="mt-1.5 text-xs text-muted">Common window {mon(item.window.common[0])} to {mon(item.window.common[1])}</div>
          {pending(item) && <div className="mt-1.5"><MonthPicker item={item} onChange={(s, e) => onPatch(item.id, { target_start: s, target_end: e })} /></div>}
        </section>
        {item.risks.length > 0 && (
          <section>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">Risks</div>
            {item.risks.map((r, k) => <p key={k} className="flex gap-1.5 text-xs leading-snug"><AlertTriangle size={12} className="mt-0.5 shrink-0 text-warn" />{r}</p>)}
          </section>
        )}
        {item.news.length > 0 && (
          <section>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">In the news</div>
            {item.news.map((n, k) => <a key={k} href={n.url} target="_blank" rel="noreferrer" className="block text-xs leading-snug hover:underline"><span className="font-semibold capitalize">{n.impact.replace("_", " ")}:</span> {n.title}</a>)}
          </section>
        )}
        {item.conflicts.length > 0 && <p className="text-xs text-warn">Needs {item.ours} in the same months as #{item.conflicts.join(", #")}.</p>}
        {item.narrative && <p className="text-xs text-muted">{item.narrative}</p>}
        {explain && <p className="text-[11px] text-faint">{explain.method}</p>}
        <textarea value={note} onChange={(e) => setNote(e.target.value)} onBlur={(e) => e.target.value !== item.note && onPatch(item.id, { note: e.target.value })}
          rows={2} maxLength={1000} placeholder="Note for the request (optional)" className="w-full resize-none rounded-xl border-2 border-line px-2.5 py-1.5 text-xs outline-none focus:border-pen" />
        <ItemButtons it={item} onPatch={onPatch} onOpenGoal={onOpenGoal} />
      </div>
    </>
  );
}

// the right-quarter panel: summary, top risks and the item list, or one item's detail
export default function PlanPanel({ me, store, id, item, onItem, onBack, onSwitch, onOpenOverlap, onOpenGoal }: {
  me: Me; store: PlanStore; id: number; item?: string; onItem: (itemId: string | null) => void; onBack: () => void;
  onSwitch: (id: number) => void; onOpenOverlap: (id: number) => void; onOpenGoal: (id: number) => void;
}) {
  const plan = store.plans[id] ?? null;
  const { patch, execute, err } = useItemActions(store, plan, onOpenGoal);
  useEffect(() => { if (!plan) store.load(id).catch(() => {}); }, [id, plan, store]);
  const items = useMemo(() => plan?.items ?? [], [plan]);
  const risks = useMemo(() => items.filter((i) => i.state !== "skipped").flatMap((i) => i.risks.map((r) => ({ r, id: i.id }))).slice(0, 3), [items]);
  const current = item ? items.find((i) => i.id === item) ?? null : null;
  const busy = store.busy != null;
  const switchTo = (h: Horizon) => store.byHorizon(h).then((p) => { onSwitch(p.id); say(`Plan for ${HORIZONS.find(([k]) => k === h)?.[1].toLowerCase()}: ${p.items.length} pairs.`, "nod"); }).catch(() => {});

  if (!plan) return <><PanelHeader title="Plan" onBack={onBack} /><p className="text-sm text-muted"><span className="dots">Loading</span></p></>;
  if (current) return <Detail plan={plan} item={current} onBack={() => onItem(null)} onPatch={patch} onOpenOverlap={onOpenOverlap} onOpenGoal={onOpenGoal} />;
  return (
    <>
      <PanelHeader title="Plan" sub={`${items.length} pair${items.length === 1 ? "" : "s"} for ${me.short}`} onBack={onBack} />
      <div className="mb-2 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
        {HORIZONS.map(([k, label]) => <button key={k} onClick={() => k !== plan.horizon && switchTo(k)} className={`flex-1 rounded-full py-1 ${plan.horizon === k ? "bg-white shadow-sm" : "text-muted"}`}>{label}</button>)}
      </div>
      {err && <p className="mb-2 rounded-xl bg-warn-soft px-3 py-1.5 text-xs text-warn">{err}</p>}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
        <PlanSummary plan={plan} />
        {risks.length > 0 && (
          <div className="rounded-2xl border-2 border-line px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-faint">Top risks</div>
            {risks.map((x, k) => <button key={k} onClick={() => onItem(x.id)} className="block w-full truncate text-left text-xs leading-snug hover:underline">#{x.id}: {x.r}</button>)}
          </div>
        )}
        {items.map((it) => (
          <div key={it.id} className={`rounded-2xl border-2 border-line px-3 py-2 ${it.state === "skipped" ? "opacity-60" : ""}`}>
            <button onClick={() => onItem(it.id)} className="block w-full text-left">
              <div className="flex items-center gap-2"><VerdictChip v={it.verdict} /><span className="text-xs text-faint">#{it.id}</span><span className="flex-1" /><StateChip s={it.state} /></div>
              <div className="mt-0.5 line-clamp-2 text-sm font-semibold leading-snug">{it.ours}</div>
              <div className="text-xs text-muted">with {it.theirs} · {it.partner_short}</div>
              <div className="mt-0.5 text-xs text-muted">{mon(it.target_start)} to {mon(it.target_end)} · <span className="font-semibold text-save">{money(it.savings)}</span> · {it.action}</div>
            </button>
            <ItemButtons it={it} onPatch={patch} onOpenGoal={onOpenGoal} />
          </div>
        ))}
      </div>
      <ExecuteButton plan={plan} busy={busy} onExecute={execute} />
    </>
  );
}
