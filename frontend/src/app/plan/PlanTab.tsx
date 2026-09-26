import { AlertTriangle, Check, ExternalLink, Flag, Map as MapIcon, RefreshCw, SkipForward } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, colorFor, usd, type Jobs, type Me, type Overlap } from "../data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { say } from "../mascot";
import { PanelHeader } from "../panels";
import { Split } from "../weather/shared";

type Horizon = "quarter" | "year" | "window";
type Range = { low: number; high: number };
type Verdict = "strong" | "possible" | "unknown" | "unlikely";
type Item = {
  id: string; opportunity_id: number; partner: string; partner_name: string; partner_short: string; ours: string; theirs: string; our_job: string; their_job: string;
  tier: string; verdict: Verdict; feasibility: number; feasibility_source: string; narrative: string | null; savings: Range;
  window: { ours: [string, string]; theirs: [string, string]; common: [string, string]; overlap_pct: number };
  target_start: string; target_end: string; weather: { target: Range; naive: Range; avoided: Range; days: Range; naive_window: [string, string] };
  hazard_strip: Record<string, number>; action: "send request" | "follow up" | "wait"; action_reason: string; request_id: number | null;
  news: { title: string; impact: string; url?: string }[]; risks: string[]; conflicts: string[]; state: "proposed" | "accepted" | "skipped"; note: string;
  goal_id: number | null; passed?: boolean; rank: number;
};
type Totals = {
  savings: Range; weather_avoided: Range; verdicts: Record<Verdict, number>; selected: number; considered: number; skipped: Record<string, number>;
  period: [string, string] | null; conflicts: number; passed: number; actions: Record<string, number>; note: string;
};
type Plan = { id: number; horizon: Horizon; version: number; items: Item[]; totals: Totals; status: string; created_at: string };
type Explain = {
  chosen_because: { feasibility: string; feasibility_score: number; feasibility_source: string; savings_usd: Range; rank: number; windows_overlap_pct: number };
  months_because: { target: [string, string]; weather_cost_usd: Range; instead_of: [string, string]; its_weather_cost_usd: Range; avoided_usd: Range; affected_days: Range; common_window: [string, string] };
  action: string; action_reason: string; risks: string[]; news: { title: string; impact: string; url?: string }[]; conflicts: string[]; method: string;
};
export type PlanFocus = { horizon?: string; item?: string; at: number };

const HORIZONS: [Horizon, string][] = [["quarter", "Next quarter"], ["year", "Next year"], ["window", "Whole window"]];
const VERDICT: Record<Verdict, { label: string; color: string; bg: string }> = {
  strong: { label: "Strong", color: "#12a36b", bg: "#dff6ec" }, possible: { label: "Possible", color: "#b8860b", bg: "#fff3d9" },
  unknown: { label: "Unknown", color: "#5e6a8a", bg: "#eef1f6" }, unlikely: { label: "Unlikely", color: "#8a94b0", bg: "#e6e9ef" },
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const money = (r: Range) => (r.low === r.high ? usd(r.low) : `${usd(r.low)} to ${usd(r.high)}`);
const mon = (s: string) => { const d = new Date(`${s.slice(0, 10)}T12:00:00`); return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`; };
const first = (s: string) => new Date(`${s.slice(0, 7)}-01T12:00:00`);
const addMonths = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth() + n, 1, 12);
const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
const lastDay = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0, 12);
const iso = (d: Date) => `${key(d)}-${String(d.getDate()).padStart(2, "0")}`;

function VerdictChip({ v }: { v: Verdict }) {
  const c = VERDICT[v];
  return <span className="rounded-full px-2 py-0.5 text-xs font-semibold" style={{ background: c.bg, color: c.color }}>{c.label}</span>;
}

function StateChip({ s }: { s: Item["state"] }) {
  if (s === "accepted") return <span className="rounded-full bg-save-soft px-2 py-0.5 text-xs font-semibold text-save">Accepted</span>;
  if (s === "skipped") return <span className="rounded-full bg-soft px-2 py-0.5 text-xs font-semibold text-muted">Skipped</span>;
  return null;
}

// the months the timeline shows: the plan's period, or the span of the chosen months for whole windows
function axis(plan: Plan): Date[] {
  const p = plan.totals.period;
  let start = p ? first(p[0]) : null, end = p ? first(p[1]) : null;
  if (!start || !end) {
    const starts = plan.items.map((i) => first(i.target_start).getTime()), ends = plan.items.map((i) => first(i.target_end).getTime());
    if (!starts.length) { const t = new Date(); return Array.from({ length: 12 }, (_, k) => addMonths(new Date(t.getFullYear(), t.getMonth(), 1, 12), k)); }
    start = new Date(Math.min(...starts)); end = new Date(Math.max(...ends));
  }
  const out: Date[] = [];
  for (let d = start; d <= end && out.length < 36; d = addMonths(d, 1)) out.push(d);
  return out;
}

function MonthPicker({ item, onChange }: { item: Item; onChange: (start: string, end: string) => void }) {
  const opts = useMemo(() => {  // any month inside the common window
    const out: Date[] = [];
    for (let d = first(item.window.common[0]); d <= first(item.window.common[1]) && out.length < 60; d = addMonths(d, 1)) out.push(d);
    return out;
  }, [item.window.common]);
  const s = key(first(item.target_start)), e = key(first(item.target_end));
  const pick = (ns: string, ne: string) => {
    const a = new Date(`${ns}-01T12:00:00`), b = new Date(`${ne}-01T12:00:00`);
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    onChange(iso(lo), iso(lastDay(hi)));
  };
  const sel = "rounded-full border-2 border-line bg-white px-2 py-0.5 text-xs font-semibold outline-none focus:border-pen";
  return (
    <span className="flex items-center gap-1 text-xs text-muted">
      <select value={s} onChange={(ev) => pick(ev.target.value, e)} className={sel} aria-label="Start month">{opts.map((d) => <option key={key(d)} value={key(d)}>{mon(iso(d))}</option>)}</select>
      to
      <select value={e} onChange={(ev) => pick(s, ev.target.value)} className={sel} aria-label="End month">{opts.map((d) => <option key={key(d)} value={key(d)}>{mon(iso(d))}</option>)}</select>
    </span>
  );
}

export default function PlanTab({ me, side, focus, onOpenOverlap, onOpenGoal }: {
  me: Me; side: React.ReactNode | null; focus?: PlanFocus | null; onOpenOverlap: (id: number) => void; onOpenGoal: (id: number) => void;
}) {
  const [horizon, setHorizon] = useState<Horizon>((focus?.horizon as Horizon) ?? "quarter");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [view, setView] = useState<"timeline" | "map">("timeline");
  const [open, setOpen] = useState<string | null>(null);
  const [explain, setExplain] = useState<Explain | null>(null);
  const [ov, setOv] = useState<{ overlaps: Overlap[]; jobs: Jobs } | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);

  const load = (h: Horizon, rebuild = false) => {
    setBusy(true); setErr(null);
    const req = rebuild ? api.send<Plan>(`/api/app/plan/build?horizon=${h}`, "POST") : api.get<Plan>(`/api/app/plan?horizon=${h}`);
    req.then((p) => {
      setPlan(p);
      const t = p.totals, label = HORIZONS.find(([k]) => k === h)?.[1].toLowerCase();
      say(p.items.length ? `Plan for ${label}: ${p.items.length} pair${p.items.length === 1 ? "" : "s"}, ${money(t.savings)} in savings.${t.note ? " I had to look further out." : ""}`
        : "No pairs to plan in this horizon. Try a longer one.", p.items.length ? "talking" : "nod");
    }).catch((e) => { setErr(String(e.message ?? e)); say("I couldn't build the plan.", "sad"); }).finally(() => setBusy(false));
  };
  useEffect(() => { load(horizon); }, [horizon]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // crewly built or explained a plan from the chat
    if (!focus) return;
    if (focus.horizon && HORIZONS.some(([k]) => k === focus.horizon)) setHorizon(focus.horizon as Horizon);
    if (focus.item) setOpen(focus.item);
  }, [focus?.at]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (view === "map" && !ov) api.overlaps().then(setOv).catch(() => {}); }, [view, ov]);
  useEffect(() => {
    if (!open || !plan) { setExplain(null); return; }
    setExplain(null);
    api.get<Explain>(`/api/app/plan/${plan.id}/explain/${open}`).then(setExplain).catch(() => {});
  }, [open, plan?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const patch = async (id: string, body: Partial<Pick<Item, "state" | "target_start" | "target_end" | "note">>) => {
    if (!plan) return;
    try {
      setPlan(await api.send<Plan>(`/api/app/plan/${plan.id}/items/${id}`, "PATCH", body));
      if (body.state === "accepted") say(`Accepted #${id}. Execute the plan when you're ready.`, "nod");
      if (body.state === "skipped") say(`Skipped #${id}.`, "nod");
    } catch (e) { setErr(String((e as Error).message ?? e)); }
  };
  const execute = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      const r = await api.send<{ task_id: number; drafted: number; plan: Plan }>(`/api/app/plan/${plan.id}/execute`, "POST");
      setPlan(r.plan);
      say(`Drafted ${r.drafted} request${r.drafted === 1 ? "" : "s"}. Review and send them from the goal panel.`, "happy");
      onOpenGoal(r.task_id);
    } catch (e) { setErr(String((e as Error).message ?? e)); say("Nothing to execute yet.", "sad"); }
    finally { setBusy(false); }
  };

  const items = useMemo(() => plan?.items ?? [], [plan]);
  const months = useMemo(() => (plan ? axis(plan) : []), [plan]);
  const accepted = items.filter((i) => i.state === "accepted" && !i.goal_id && !i.request_id);
  const risks = useMemo(() => items.filter((i) => i.state !== "skipped").flatMap((i) => i.risks.map((r) => ({ r, id: i.id }))).slice(0, 3), [items]);
  const current = open ? items.find((i) => i.id === open) ?? null : null;

  const scene = useMemo<Scene>(() => {
    if (!ov) return {};
    const lines: GeoJSON.Feature[] = [], points: GeoJSON.Feature[] = [];
    const byId = new Map(ov.overlaps.map((o) => [o.id, o]));
    const jobs = new Map(ov.jobs.features.map((f) => [f.properties.id, f]));
    for (const it of items) {
      const o = byId.get(it.opportunity_id);
      const color = VERDICT[it.verdict].color, on = !open || open === it.id;
      for (const jid of [it.our_job, it.their_job]) {
        const f = jobs.get(jid);
        if (!f) continue;
        const props = { color: colorFor(f.properties.org_id), width: 3, radius: 5, opacity: on ? 0.9 : 0.2, title: `<b>${esc(f.properties.name)}</b>` };
        (f.geometry?.type === "Point" ? points : lines).push({ type: "Feature", geometry: f.geometry, properties: props });
      }
      if (o) {
        const title = `<b>#${o.id} ${esc(VERDICT[it.verdict].label)}</b><br/>${esc(it.ours)}<br/><span style="color:#5e6a8a">with ${esc(it.theirs)} · ${esc(mon(it.target_start))} to ${esc(mon(it.target_end))}</span>`;
        lines.push({ type: "Feature", geometry: o.link, properties: { color, width: 3, dash: true, opacity: on ? 1 : 0.2, title, pick: `plan:${it.id}` } });
        const c = o.link.coordinates, a = c[0], b = c[c.length - 1];
        points.push({ type: "Feature", geometry: { type: "Point", coordinates: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] },
          properties: { color, radius: open === it.id ? 9 : 6, stroke: "#111014", opacity: on ? 1 : 0.25, title, pick: `plan:${it.id}` } });
      }
    }
    return { lines: { type: "FeatureCollection", features: lines }, points: { type: "FeatureCollection", features: points } };
  }, [ov, items, open]);
  useEffect(() => {
    if (view !== "map" || !ov || !items.length) return;
    const b = bboxOf([scene.lines, scene.points]);
    if (b) setFit({ bbox: b, key: `plan${plan?.id}${view}` });
  }, [view, ov, plan?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  const today = new Date();
  const todayIdx = months.findIndex((m) => m.getFullYear() === today.getFullYear() && m.getMonth() === today.getMonth());

  const timeline = (
    <div className="pen-box relative flex h-full w-full flex-col overflow-hidden bg-white">
      <div className="flex items-center gap-2 border-b-2 border-line px-4 py-2">
        <span className="font-logo text-base font-semibold">{plan ? `Version ${plan.version}` : "Plan"}</span>
        <span className="text-xs text-muted">{plan?.totals.period ? `${mon(plan.totals.period[0])} to ${mon(plan.totals.period[1])}` : "whole build windows"}</span>
        <span className="flex-1" />
        <button onClick={() => setView("map")} className="flex items-center gap-1 rounded-full border-2 border-line px-2.5 py-0.5 text-xs font-semibold hover:border-pen"><MapIcon size={13} /> Map</button>
        <button onClick={() => load(horizon, true)} disabled={busy} className="flex items-center gap-1 rounded-full border-2 border-line px-2.5 py-0.5 text-xs font-semibold hover:border-pen disabled:opacity-50"><RefreshCw size={13} /> Rebuild</button>
      </div>
      {!plan && <div className="grid flex-1 place-items-center text-muted"><span className="dots">{busy ? "Planning" : "Loading"}</span></div>}
      {plan && !items.length && <div className="grid flex-1 place-items-center px-8 text-center text-sm text-muted">No pairs to plan for this horizon. {plan.totals.note || "Try a longer horizon."}</div>}
      {plan && items.length > 0 && (
        <div className="thin-scroll flex-1 overflow-auto">
          <div className="min-w-[640px]">
            <div className="sticky top-0 z-10 grid border-b border-line bg-white text-[10px] font-semibold uppercase tracking-wide text-faint" style={{ gridTemplateColumns: `220px repeat(${months.length}, minmax(0, 1fr))` }}>
              <div className="px-3 py-1">Pair</div>
              {months.map((m) => <div key={key(m)} className={`border-l border-line px-1 py-1 ${m.getMonth() === 0 ? "text-ink" : ""}`}>{MONTHS[m.getMonth()]}{m.getMonth() === 0 || m === months[0] ? ` ${String(m.getFullYear()).slice(2)}` : ""}</div>)}
            </div>
            {items.map((it) => {
              const s = months.findIndex((m) => key(m) === it.target_start.slice(0, 7)), e = months.findIndex((m) => key(m) === it.target_end.slice(0, 7));
              const from = s >= 0 ? s : 0, to = e >= 0 ? e : months.length - 1;
              const dim = it.state === "skipped";
              return (
                <div key={it.id} className={`grid items-stretch border-b border-line hover:bg-soft ${open === it.id ? "bg-grape-soft/60" : ""}`}
                  style={{ gridTemplateColumns: `220px repeat(${months.length}, minmax(0, 1fr))` }}>
                  <button onClick={() => setOpen(it.id)} className="min-w-0 px-3 py-2 text-left">
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
                        {inBar && (
                          <button onClick={() => setOpen(it.id)} aria-label={`Open #${it.id}`}
                            className={`absolute inset-y-2 ${k === from ? "left-1 rounded-l-full" : "left-0"} ${k === to ? "right-1 rounded-r-full" : "right-0"} ${dim ? "opacity-30" : ""}`}
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
      </div>
    </div>
  );

  const map = (
    <MapPane scene={scene} fit={fit} onPick={(p) => p.startsWith("plan:") && setOpen(p.slice(5))}>
      <button onClick={() => setView("timeline")} className="absolute right-3 top-3 z-10 flex items-center gap-1 rounded-full border-2 border-pen bg-white px-2.5 py-1 text-xs font-semibold">Timeline</button>
    </MapPane>
  );

  const list = plan && (
    <>
      <PanelHeader title="Plan" sub={`${items.length} pair${items.length === 1 ? "" : "s"} for ${me.short}`} />
      <div className="mb-2 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
        {HORIZONS.map(([k, label]) => <button key={k} onClick={() => setHorizon(k)} className={`flex-1 rounded-full py-1 ${horizon === k ? "bg-white shadow-sm" : "text-muted"}`}>{label}</button>)}
      </div>
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
        <div className="rounded-2xl bg-save-soft/70 px-3 py-2.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-faint">Expected savings</div>
          <div className="font-logo text-2xl font-semibold text-save">{money(plan.totals.savings)}</div>
          <div className="text-xs text-muted">plus {money(plan.totals.weather_avoided)} of weather cost avoided by the chosen months</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(Object.keys(VERDICT) as Verdict[]).filter((v) => plan.totals.verdicts[v]).map((v) => <span key={v} className="rounded-full px-2 py-0.5 text-xs font-semibold" style={{ background: VERDICT[v].bg, color: VERDICT[v].color }}>{plan.totals.verdicts[v]} {VERDICT[v].label.toLowerCase()}</span>)}
            {plan.totals.conflicts > 0 && <span className="rounded-full bg-warn-soft px-2 py-0.5 text-xs font-semibold text-warn">{plan.totals.conflicts} conflict{plan.totals.conflicts === 1 ? "" : "s"}</span>}
            {plan.totals.passed > 0 && <span className="rounded-full bg-soft px-2 py-0.5 text-xs font-semibold text-muted">{plan.totals.passed} filed window{plan.totals.passed === 1 ? "" : "s"} already passed</span>}
          </div>
          {plan.totals.note && <p className="mt-1.5 text-xs text-muted">{plan.totals.note}</p>}
        </div>
        {risks.length > 0 && (
          <div className="rounded-2xl border-2 border-line px-3 py-2">
            <div className="text-xs font-semibold uppercase tracking-wide text-faint">Top risks</div>
            {risks.map((x, k) => <button key={k} onClick={() => setOpen(x.id)} className="block w-full truncate text-left text-xs leading-snug hover:underline">#{x.id}: {x.r}</button>)}
          </div>
        )}
        {items.map((it) => (
          <div key={it.id} className={`rounded-2xl border-2 px-3 py-2 ${open === it.id ? "border-pen bg-grape-soft/40" : "border-line"} ${it.state === "skipped" ? "opacity-60" : ""}`}>
            <button onClick={() => setOpen(it.id)} className="block w-full text-left">
              <div className="flex items-center gap-2"><VerdictChip v={it.verdict} /><span className="text-xs text-faint">#{it.id}</span><span className="flex-1" /><StateChip s={it.state} /></div>
              <div className="mt-0.5 line-clamp-2 text-sm font-semibold leading-snug">{it.ours}</div>
              <div className="text-xs text-muted">with {it.theirs} · {it.partner_short}</div>
              <div className="mt-0.5 text-xs text-muted">{mon(it.target_start)} to {mon(it.target_end)} · <span className="font-semibold text-save">{money(it.savings)}</span> · {it.action}</div>
            </button>
            {it.state !== "skipped" && !it.goal_id && !it.request_id && (
              <div className="mt-1.5 flex items-center gap-1.5">
                {it.state !== "accepted" && <button onClick={() => patch(it.id, { state: "accepted" })} className="flex items-center gap-1 rounded-full bg-save px-2.5 py-0.5 text-xs font-semibold text-white"><Check size={12} /> Accept</button>}
                <button onClick={() => patch(it.id, { state: "skipped" })} className="flex items-center gap-1 rounded-full border-2 border-line px-2.5 py-0.5 text-xs font-semibold hover:border-pen"><SkipForward size={12} /> Skip</button>
                <MonthPicker item={it} onChange={(s, e) => patch(it.id, { target_start: s, target_end: e })} />
              </div>
            )}
            {it.state === "skipped" && <button onClick={() => patch(it.id, { state: "proposed" })} className="mt-1 text-xs font-semibold text-grape underline">Bring back</button>}
            {it.goal_id && <button onClick={() => onOpenGoal(it.goal_id!)} className="mt-1 flex items-center gap-1 text-xs font-semibold text-grape hover:underline"><Flag size={12} /> In goal {it.goal_id}</button>}
          </div>
        ))}
      </div>
      <button onClick={execute} disabled={busy || !accepted.length} className="pen-btn mt-2 flex w-full items-center justify-center gap-2 bg-grape px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
        <Flag size={15} /> Execute {accepted.length ? `${accepted.length} accepted` : "accepted items"}
      </button>
    </>
  );

  const detail = current && (
    <>
      <PanelHeader title={`#${current.id} ${current.partner_short}`} sub={<span className="flex items-center gap-2"><VerdictChip v={current.verdict} /><StateChip s={current.state} /></span>} onBack={() => setOpen(null)} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
        <div className="rounded-2xl border-2 border-line px-3 py-2">
          <div className="text-sm font-semibold leading-snug">{current.ours}</div>
          <div className="text-xs text-muted">with {current.theirs} ({current.partner_name})</div>
          <button onClick={() => onOpenOverlap(current.opportunity_id)} className="mt-1 flex items-center gap-1 text-xs font-semibold text-grape hover:underline"><ExternalLink size={12} /> Open overlap</button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Savings</div><div className="font-logo text-base font-semibold text-save">{money(current.savings)}</div></div>
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Feasibility</div><div className="font-logo text-base font-semibold">{Math.round(current.feasibility * 100)}%</div><div className="text-[11px] text-muted">{current.feasibility_source}</div></div>
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Windows overlap</div><div className="font-logo text-base font-semibold">{current.window.overlap_pct}%</div></div>
          <div className="rounded-xl bg-soft px-2.5 py-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Action</div><div className="text-sm font-semibold capitalize">{current.action}</div><div className="text-[11px] text-muted">{current.action_reason}</div></div>
        </div>
        <section className="rounded-2xl bg-grape-soft/50 px-3 py-2.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-faint">Why these months</div>
          <div className="font-logo text-lg font-semibold">{mon(current.target_start)} to {mon(current.target_end)}</div>
          <p className="text-xs text-muted">
            About {money(current.weather.target)} of weather cost, against {money(current.weather.naive)} starting {mon(current.weather.naive_window[0])}: {money(current.weather.avoided)} avoided.
            {" "}{current.weather.days.low === current.weather.days.high ? current.weather.days.high : `${current.weather.days.low} to ${current.weather.days.high}`} affected days expected.
          </p>
          <div className="mt-1.5 text-xs text-muted">Common window {mon(current.window.common[0])} to {mon(current.window.common[1])}</div>
          {current.state !== "skipped" && !current.goal_id && <div className="mt-1.5"><MonthPicker item={current} onChange={(s, e) => patch(current.id, { target_start: s, target_end: e })} /></div>}
        </section>
        {current.risks.length > 0 && (
          <section>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">Risks</div>
            {current.risks.map((r, k) => <p key={k} className="flex gap-1.5 text-xs leading-snug"><AlertTriangle size={12} className="mt-0.5 shrink-0 text-warn" />{r}</p>)}
          </section>
        )}
        {current.news.length > 0 && (
          <section>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">In the news</div>
            {current.news.map((n, k) => <a key={k} href={n.url} target="_blank" rel="noreferrer" className="block text-xs leading-snug hover:underline"><span className="font-semibold capitalize">{n.impact.replace("_", " ")}:</span> {n.title}</a>)}
          </section>
        )}
        {current.conflicts.length > 0 && <p className="text-xs text-warn">Needs {current.ours} in the same months as #{current.conflicts.join(", #")}.</p>}
        {current.narrative && <p className="text-xs text-muted">{current.narrative}</p>}
        {explain && <p className="text-[11px] text-faint">{explain.method}</p>}
        <textarea value={current.note} onChange={(e) => setPlan((p) => p && { ...p, items: p.items.map((i) => (i.id === current.id ? { ...i, note: e.target.value } : i)) })}
          onBlur={(e) => patch(current.id, { note: e.target.value })} rows={2} maxLength={1000} placeholder="Note for the request (optional)"
          className="w-full resize-none rounded-xl border-2 border-line px-2.5 py-1.5 text-xs outline-none focus:border-pen" />
        {current.state !== "skipped" && !current.goal_id && !current.request_id && (
          <div className="flex gap-2">
            {current.state !== "accepted" && <button onClick={() => patch(current.id, { state: "accepted" })} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-save px-3 py-1.5 text-sm font-semibold text-white"><Check size={15} /> Accept</button>}
            <button onClick={() => patch(current.id, { state: "skipped" })} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-white px-3 py-1.5 text-sm font-semibold"><SkipForward size={15} /> Skip</button>
          </div>
        )}
        {current.goal_id && <button onClick={() => onOpenGoal(current.goal_id!)} className="pen-btn flex items-center justify-center gap-2 bg-white px-3 py-1.5 text-sm font-semibold"><Flag size={15} /> Open goal {current.goal_id}</button>}
      </div>
    </>
  );

  return (
    <>
      {err && <p className="mb-2 rounded-xl bg-warn-soft px-3 py-1.5 text-xs text-warn">{err}</p>}
      <Split map={view === "map" ? map : timeline} side={side ?? (current ? detail : list ?? <div className="text-sm text-muted"><span className="dots">Loading</span></div>)} />
    </>
  );
}
