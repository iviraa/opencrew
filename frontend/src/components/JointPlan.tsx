import { useEffect, useState } from "react";
import { api, type Headline, type JointPlan as Plan, type PlanConstraints, type PlanMetrics } from "../api";
import { usd } from "../format";

type Props = {
  plan: Plan | null;
  solving: boolean;
  onSolve: (c: PlanConstraints) => void;
  pending: { constraints: PlanConstraints; rules: string[] } | null;
  onDiscardPending: () => void;
  selectedId: number | null;
  onSelect: (id: number) => void;
};

const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const ROWS: [keyof PlanMetrics, string][] = [["mobilizations", "Crew mobilizations (own utility)"], ["specialty_mobilizations", "Specialty mobilizations"],
  ["shared_bursts", "Specialty jobs shared across utilities"], ["yards", "Staging yards"], ["slip_months", "Months of slip"],
  ["late_projects", "Projects late"], ["cost_k", "Modeled cost ($k)"]];

function HeadlineCard({ h, title, note, tone }: { h: Headline; title: string; note: string; tone: "emerald" | "amber" }) {
  const box = tone === "emerald" ? "bg-emerald-50 ring-emerald-200 text-emerald-900" : "bg-amber-50 ring-amber-200 text-amber-900";
  const types = Object.values(h.specialty ?? {}).filter((s) => s.before !== s.after);
  return (
    <div className={`flex-1 rounded-lg p-3 ring-1 ${box}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide opacity-70">{title}</div>
      <div className="text-base font-semibold leading-5">{h.mobilizations_cut_pct}% fewer mobilizations</div>
      <div className="mt-0.5">{h.mobilizations_before} → {h.mobilizations_after} total · {h.yards_before} → {h.yards_after} yards</div>
      {types.length > 0 && <div className="mt-0.5">{types.map((s) => `${s.label} ${s.before} → ${s.after}`).join(" · ")}</div>}
      {h.crew_mobilizations_after !== h.crew_mobilizations_before && <div className="mt-0.5">crews {h.crew_mobilizations_before} → {h.crew_mobilizations_after}</div>}
      <div className="mt-1 font-semibold">saves {usd(h.savings_low)}–{usd(h.savings_high)} · {h.late_projects} late</div>
      <div className="mt-1 text-[10px] opacity-80">{note}</div>
    </div>
  );
}

export default function JointPlan({ plan, solving, onSolve, pending, onDiscardPending, selectedId, onSelect }: Props) {
  const [draft, setDraft] = useState<PlanConstraints | null>(null);
  const [why, setWhy] = useState<Record<number, string>>({});
  const [asking, setAsking] = useState<number | null>(null);
  useEffect(() => { if (plan) setDraft(structuredClone(plan.constraints)); }, [plan]);

  if (!plan || !draft) return <div className="px-4 py-3 text-sm text-slate-400">{solving ? "Solving the joint schedule…" : "Loading the joint plan…"}</div>;
  const crews = plan.headline?.crews ?? {};
  const setCount = (org: string, year: string, n: number) =>
    setDraft({ ...draft, crew_counts: { ...draft.crew_counts, [org]: { ...(draft.crew_counts[org] ?? {}), [year]: n } } });
  const setBurst = (key: string, patch: Partial<PlanConstraints["bursts"][string]>) =>
    setDraft({ ...draft, bursts: { ...draft.bursts, [key]: { ...draft.bursts[key], ...patch } } });
  const explain = (id: number) => {
    onSelect(id);
    if (why[id]) return;
    setAsking(id);
    api.explainPlan(id).then((r) => setWhy((w) => ({ ...w, [id]: r.decisions[0]?.sentence ?? "" }))).finally(() => setAsking(null));
  };
  const h = plan.headline;
  const jc = h?.joint_contracting;
  const solver = h?.solver;

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3 text-xs">
      <p className="text-slate-500">
        OR-Tools CP-SAT schedules every phase for the {plan.baseline?.projects ?? 0} projects in cross-utility pairs, once for each utility alone and once
        jointly. General crews stay with their own utility; heavy haul, crane lifts, wire stringing and commissioning can be shared within a
        {" "}{draft.crew_drive_min} minute drive. Durations, costs and crew counts are editable assumptions, not public data.
      </p>
      {plan.status === "infeasible" && <div className="rounded bg-red-50 px-3 py-2 text-red-700 ring-1 ring-red-200">{plan.problem}</div>}
      {h && plan.baseline && plan.coordinated && (
        <>
          <div className="flex gap-2">
            <HeadlineCard h={h} title="Strict plan (default)" tone="emerald" note="Specialty crews and yards shared; no assumption about contractors." />
            {jc && <HeadlineCard h={jc} title="Joint contracting (assumption)" tone="amber" note={`${jc.assumption} ${jc.contractor_pairs} contractor pair(s).`} />}
          </div>
          {solver && (
            <p className="text-[11px] text-slate-500">
              Separate plans: {solver.separate === "optimal" ? "proven optimal" : "best found"} · coordinated: {solver.coordinated === "optimal"
                ? "proven optimal" : `best found in the time limit (a proven optimum could be at most $${solver.coordinated_gap_k.toLocaleString()}k cheaper)`}.
            </p>
          )}
          <table className="w-full">
            <thead><tr className="text-left text-slate-500"><th className="py-1 font-medium" /><th className="font-medium">Separate</th><th className="font-medium">Coordinated</th></tr></thead>
            <tbody>
              {ROWS.map(([key, label]) => {
                const a = Number(plan.baseline![key] ?? 0), b = Number(plan.coordinated![key] ?? 0);
                const better = key === "shared_bursts" ? b > a : b < a;
                return (
                  <tr key={key} className="border-t border-slate-100">
                    <td className="py-1 text-slate-600">{label}</td>
                    <td>{a.toLocaleString()}</td>
                    <td className={better ? "font-semibold text-emerald-700" : ""}>{b.toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {pending && (
        <div className="rounded-lg bg-blue-50 p-3 ring-1 ring-blue-200">
          <div className="font-semibold text-blue-900">Crewly proposed these rules</div>
          <ul className="mt-1 list-disc pl-4 text-blue-900">{pending.rules.map((r) => <li key={r}>{r}</li>)}</ul>
          <div className="mt-2 flex gap-2">
            <button onClick={() => { onSolve(pending.constraints); onDiscardPending(); }} disabled={solving}
              className="rounded bg-blue-600 px-2 py-1 font-semibold text-white disabled:opacity-50">Confirm and solve</button>
            <button onClick={onDiscardPending} className="rounded bg-white px-2 py-1 font-medium ring-1 ring-slate-300">Discard</button>
          </div>
        </div>
      )}

      <section className="space-y-2 rounded-lg p-3 ring-1 ring-slate-200">
        <h3 className="font-semibold uppercase tracking-wide text-slate-500">Constraints</h3>
        {([["max_slip_months", "Max slip past in-service", 24, "months"], ["max_advance_months", "Max months started early", 24, "months"],
          ["burst_gap_weeks", "Longest wait for a shared specialty crew", 12, "weeks"]] as const).map(([key, label, max, unit]) => (
          <label key={key} className="block">
            <div className="flex justify-between"><span>{label}</span><b>{draft[key]} {unit}</b></div>
            <input type="range" min={0} max={max} value={draft[key]} onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })} className="w-full accent-slate-900" />
          </label>
        ))}
        <label className="flex items-start gap-2 rounded bg-amber-50 p-2 ring-1 ring-amber-200">
          <input type="checkbox" checked={draft.joint_contracting} onChange={(e) => setDraft({ ...draft, joint_contracting: e.target.checked })} className="mt-0.5" />
          <span><b>Joint contracting</b> (assumption, off by default): one contractor serves both utilities' jobs that run at the same time within a
            {" "}{draft.crew_drive_min} minute drive. Shown as a separate headline.</span>
        </label>
        <div>
          <div className="mb-1">Specialty crews <span className="text-slate-400">(weeks · typical window in its phase · $k per mobilization)</span></div>
          {Object.entries(draft.bursts ?? {}).map(([key, b]) => (
            <div key={key} className="mb-1 flex flex-wrap items-center gap-1 rounded bg-slate-50 p-1.5 ring-1 ring-slate-200">
              <input type="checkbox" checked={b.enabled} onChange={(e) => setBurst(key, { enabled: e.target.checked })} />
              <span className="w-24 font-medium capitalize">{b.label}</span>
              <input type="number" min={1} max={26} value={b.weeks} onChange={(e) => setBurst(key, { weeks: Number(e.target.value) })}
                className="w-10 rounded border border-slate-300 px-1" title="weeks" />
              <span className="text-slate-400">wk</span>
              {[0, 1].map((i) => (
                <input key={i} type="number" min={0} max={100} step={5} value={Math.round(b.window[i] * 100)} title={i ? "window end %" : "window start %"}
                  onChange={(e) => setBurst(key, { window: (i ? [b.window[0], Number(e.target.value) / 100] : [Number(e.target.value) / 100, b.window[1]]) as [number, number] })}
                  className="w-11 rounded border border-slate-300 px-1" />
              ))}
              <span className="text-slate-400">% of {b.phase}</span>
              {(["mob_low_k", "mob_high_k"] as const).map((k) => (
                <input key={k} type="number" min={0} step={10} value={b[k]} title={k === "mob_low_k" ? "low $k" : "high $k"}
                  onChange={(e) => setBurst(key, { [k]: Number(e.target.value) })} className="w-12 rounded border border-slate-300 px-1" />
              ))}
            </div>
          ))}
        </div>
        <div>
          <div className="mb-1">Crews per utility per year</div>
          {Object.entries(crews).map(([org, years]) => (
            <div key={org} className="mb-1 flex flex-wrap items-center gap-1">
              <span className="w-10 font-semibold uppercase">{org}</span>
              {Object.keys(years).sort().map((y) => (
                <label key={y} className="flex items-center gap-0.5 text-[10px] text-slate-500">
                  {y.slice(2)}
                  <input type="number" min={0} max={30} value={draft.crew_counts[org]?.[y] ?? years[y]}
                    onChange={(e) => setCount(org, y, Number(e.target.value))} className="w-9 rounded border border-slate-300 px-1 text-xs text-slate-900" />
                </label>
              ))}
            </div>
          ))}
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span>Outage blackouts</span>
            <button onClick={() => setDraft({ ...draft, blackouts: [...draft.blackouts, { site: "*", months: [6, 7, 8], phase_kind: "energization" }] })}
              className="rounded bg-slate-100 px-1.5 py-0.5 hover:bg-slate-200">Add</button>
          </div>
          {draft.blackouts.map((b, i) => (
            <div key={i} className="mb-1 rounded bg-slate-50 p-1.5 ring-1 ring-slate-200">
              <div className="flex gap-1">
                <input value={b.site} onChange={(e) => setDraft({ ...draft, blackouts: draft.blackouts.map((x, j) => (j === i ? { ...x, site: e.target.value } : x)) })}
                  placeholder="site name or *" className="min-w-0 flex-1 rounded border border-slate-300 px-1" />
                <button onClick={() => setDraft({ ...draft, blackouts: draft.blackouts.filter((_, j) => j !== i) })} className="px-1 text-slate-400">✕</button>
              </div>
              <div className="mt-1 flex gap-0.5">
                {MONTHS.map((m, k) => {
                  const on = b.months.includes(k + 1);
                  return (
                    <button key={k} onClick={() => setDraft({ ...draft, blackouts: draft.blackouts.map((x, j) => (j === i
                      ? { ...x, months: on ? x.months.filter((n) => n !== k + 1) : [...x.months, k + 1].sort((p, q) => p - q) } : x)) })}
                      className={`w-5 rounded text-[10px] ${on ? "bg-slate-900 text-white" : "bg-white ring-1 ring-slate-200"}`}>{m}</button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        <button onClick={() => onSolve(draft)} disabled={solving} className="w-full rounded-md bg-slate-900 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
          {solving ? "Solving…" : "Solve again"}
        </button>
      </section>

      <section>
        <h3 className="mb-1 font-semibold uppercase tracking-wide text-slate-500">Decisions</h3>
        <ul className="space-y-1.5">
          {[...plan.decisions].sort((a, b) => Number(b.decision === "share") - Number(a.decision === "share")).map((d) => (
            <li key={d.opportunity_id}>
              <button onClick={() => explain(d.opportunity_id)}
                className={`w-full rounded px-2 py-1.5 text-left ring-1 ${d.opportunity_id === selectedId ? "bg-blue-50 ring-blue-200" : "ring-slate-200 hover:bg-slate-50"}`}>
                <div className="flex items-center gap-1.5">
                  <span className={`shrink-0 rounded px-1 text-[10px] font-semibold ${d.decision === "share" ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
                    {d.decision === "share" ? `shared ${(d.shared ?? []).join(", ")}` : "separate"}
                  </span>
                  {d.contractor && <span className="shrink-0 rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">contractor</span>}
                  <span className="truncate">#{d.opportunity_id} {d.a} / {d.b}</span>
                </div>
                <div className="mt-0.5 text-slate-600">{asking === d.opportunity_id ? "Re-solving with a specialty crew forced to serve both…" : why[d.opportunity_id] || d.sentence}</div>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
