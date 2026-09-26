import { Handshake, Plus, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Headline, type JointPlan as Plan, type PlanConstraints, type PlanMetrics } from "../api";
import { usd } from "../format";
import { Button, Section } from "./ui";
import { Bubble, NumberField, Slider } from "./ui-plan";

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
const ROWS: [keyof PlanMetrics, string][] = [["mobilizations", "Crew trips (own utility)"], ["specialty_mobilizations", "Specialty crew trips"],
  ["shared_bursts", "Specialty jobs shared across utilities"], ["yards", "Staging yards"], ["slip_months", "Months of delay"],
  ["late_projects", "Projects late"], ["cost_k", "Modeled cost ($k)"]];

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function story(h: Headline) {
  const trips = Object.values(h.specialty ?? {}).reduce((n, s) => n + (s.before - s.after), 0);
  const yards = h.yards_before - h.yards_after;
  const crews = h.crew_mobilizations_before - h.crew_mobilizations_after;
  const parts = [trips > 0 && `${plural(trips, "fewer trip")} for specialty crews`, crews > 0 && `${plural(crews, "fewer crew trip")}`,
    yards > 0 && `${plural(yards, "shared yard")}`, h.late_projects === 0 ? "nobody late" : `${plural(h.late_projects, "project")} late`];
  return parts.filter(Boolean).join(", ");
}

export default function JointPlan({ plan, solving, onSolve, pending, onDiscardPending, selectedId, onSelect }: Props) {
  const [draft, setDraft] = useState<PlanConstraints | null>(null);
  const [why, setWhy] = useState<Record<number, string>>({});
  const [asking, setAsking] = useState<number | null>(null);
  useEffect(() => { if (plan) setDraft(structuredClone(plan.constraints)); }, [plan]);

  if (!plan || !draft) {
    return (
      <div className="px-5 py-8 text-center">
        <div className="display text-[18px] font-semibold">{solving ? "Working out the best joint schedule…" : "Loading the joint plan…"}</div>
        <p className="mt-1 text-[14px] text-muted">The first solve takes about half a minute. After that it is instant.</p>
      </div>
    );
  }
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
  const decisions = [...plan.decisions].sort((a, b) => Number(b.decision === "share") - Number(a.decision === "share"));

  return (
    <div className="px-5 pb-6 pt-4">
      {plan.status === "infeasible" && <div className="mb-4 rounded-2xl bg-gpc-soft px-4 py-3 text-[14px] text-[#b42323]">{plan.problem}</div>}

      {h && plan.baseline && plan.coordinated && (
        <>
          <div className="rounded-[22px] bg-save-soft px-5 py-4">
            <div className="text-[14px] text-save">Working together saves</div>
            <div className="display text-[32px] font-semibold leading-tight text-save">{usd(h.savings_low)}–{usd(h.savings_high)}</div>
            <p className="mt-1 text-[15px] text-ink">{story(h)}.</p>
            <p className="mt-2 text-[13px] text-muted">
              Specialty crews (heavy haul, cranes, stringing, commissioning) and yards are shared when sites are within a {draft.crew_drive_min} minute drive.
              Everyday crews stay with their own utility.
            </p>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <Bubble label="Each utility alone" value={plural(plan.baseline.all_mobilizations ?? plan.baseline.mobilizations, "trip")} sub={`${plural(plan.baseline.yards, "yard")}, ${plural(plan.baseline.late_projects, "late project")}`} />
            <Bubble tone="desc" label="Together" value={plural(plan.coordinated.all_mobilizations ?? plan.coordinated.mobilizations, "trip")} sub={`${plural(plan.coordinated.yards, "yard")}, ${plural(plan.coordinated.late_projects, "late project")}`} />
          </div>

          {jc && (
            <div className="mt-3 rounded-[18px] bg-crew-soft px-4 py-3">
              <div className="flex items-center gap-2 text-[14px] font-semibold text-[#9a5b00]"><Handshake size={16} /> If one contractor served both utilities</div>
              <div className="display mt-0.5 text-[20px] font-semibold text-ink">{usd(jc.savings_low)}–{usd(jc.savings_high)}</div>
              <div className="text-[13px] text-muted">{jc.mobilizations_cut_pct}% fewer trips. This is an assumption, not the default plan.</div>
            </div>
          )}

          {solver && (
            <p className="mt-3 text-[13px] text-muted">
              {solver.separate === "optimal" ? "The separate plans are proven best, so the comparison is fair. "
                : `The separate plans are the best found in time (a perfect solo plan could be at most $${(solver.separate_gap_k ?? 0).toLocaleString()}k cheaper). `}
              {solver.coordinated === "optimal" ? "The joint plan is proven best too."
                : `The joint plan is the best found in the time limit; a perfect plan could save at most $${solver.coordinated_gap_k.toLocaleString()}k more.`}
            </p>
          )}
        </>
      )}

      {pending && (
        <div className="mt-4 rounded-[18px] bg-desc-soft px-4 py-3">
          <div className="flex items-center gap-2 text-[15px] font-semibold text-desc"><Sparkles size={16} /> Crewly suggested new rules</div>
          <ul className="mt-1.5 list-disc pl-5 text-[14px] text-ink">{pending.rules.map((r) => <li key={r}>{r}</li>)}</ul>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => { onSolve(pending.constraints); onDiscardPending(); }} disabled={solving}>Apply and re-plan</Button>
            <Button variant="ghost" onClick={onDiscardPending}>Discard</Button>
          </div>
        </div>
      )}

      <div className="mt-5">
        {h && plan.baseline && plan.coordinated && (
          <Section title="See the numbers">
            <table className="w-full text-[14px]">
              <thead><tr className="text-left text-[13px] text-muted"><th className="pb-1.5 font-medium" /><th className="pb-1.5 font-medium">Alone</th><th className="pb-1.5 font-medium">Together</th></tr></thead>
              <tbody>
                {ROWS.map(([key, label]) => {
                  const a = Number(plan.baseline![key] ?? 0), b = Number(plan.coordinated![key] ?? 0);
                  const better = key === "shared_bursts" ? b > a : b < a;
                  return (
                    <tr key={key} className="border-t border-line">
                      <td className="py-2 pr-2 text-muted">{label}</td>
                      <td className="py-2">{a.toLocaleString()}</td>
                      <td className={`py-2 ${better ? "font-semibold text-save" : ""}`}>{b.toLocaleString()}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Section>
        )}

        <Section title="Change the rules">
          <div className="space-y-4">
            <Slider label="Longest delay allowed" value={draft.max_slip_months} unit="months" max={24} onChange={(n) => setDraft({ ...draft, max_slip_months: n })} />
            <Slider label="Start early by at most" value={draft.max_advance_months} unit="months" max={24} onChange={(n) => setDraft({ ...draft, max_advance_months: n })} />
            <Slider label="Longest wait for a shared specialty crew" value={draft.burst_gap_weeks} unit="weeks" max={12} onChange={(n) => setDraft({ ...draft, burst_gap_weeks: n })} />

            <label className="flex cursor-pointer items-start gap-3 rounded-[18px] bg-crew-soft px-4 py-3">
              <input type="checkbox" checked={draft.joint_contracting} onChange={(e) => setDraft({ ...draft, joint_contracting: e.target.checked })} className="mt-1 h-4 w-4 accent-[#ffb020]" />
              <span className="text-[14px]"><b>Try joint contracting</b><br />
                <span className="text-muted">Assume one contractor serves both utilities' jobs that run at the same time within a {draft.crew_drive_min} minute drive. Shown as its own result.</span></span>
            </label>

            <div>
              <div className="mb-2 text-[14px] font-semibold">Specialty crews</div>
              <div className="space-y-2">
                {Object.entries(draft.bursts ?? {}).map(([key, b]) => (
                  <div key={key} className={`rounded-[16px] px-3 py-2.5 ring-1 ring-line ${b.enabled ? "bg-surface" : "bg-soft opacity-70"}`}>
                    <label className="flex items-center gap-2 text-[14px] font-semibold capitalize">
                      <input type="checkbox" checked={b.enabled} onChange={(e) => setBurst(key, { enabled: e.target.checked })} className="h-4 w-4 accent-[#2f6bff]" />
                      {b.label}
                    </label>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px] text-muted">
                      <span className="flex items-center gap-1.5"><NumberField value={b.weeks} min={1} max={26} width="w-14" title="weeks on site" onChange={(n) => setBurst(key, { weeks: n })} /> weeks</span>
                      <span className="flex items-center gap-1.5">during {b.phase}, from
                        <NumberField value={Math.round(b.window[0] * 100)} min={0} max={100} step={5} width="w-16" title="window start %" onChange={(n) => setBurst(key, { window: [n / 100, b.window[1]] })} />
                        to <NumberField value={Math.round(b.window[1] * 100)} min={0} max={100} step={5} width="w-16" title="window end %" onChange={(n) => setBurst(key, { window: [b.window[0], n / 100] })} />%
                      </span>
                      <span className="flex items-center gap-1.5">each trip $
                        <NumberField value={b.mob_low_k} min={0} step={10} width="w-16" title="low $k" onChange={(n) => setBurst(key, { mob_low_k: n })} />
                        to <NumberField value={b.mob_high_k} min={0} step={10} width="w-16" title="high $k" onChange={(n) => setBurst(key, { mob_high_k: n })} />k
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="mb-2 text-[14px] font-semibold">Crews each utility has, by year</div>
              {Object.entries(crews).map(([org, years]) => (
                <div key={org} className="mb-2">
                  <div className={`mb-1 text-[13px] font-semibold ${org === "desc" ? "text-desc" : "text-[#d93b3b]"}`}>{org === "desc" ? "Dominion Energy SC" : "Georgia Power"}</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.keys(years).sort().map((y) => (
                      <label key={y} className="flex items-center gap-1 text-[12px] text-muted">
                        {y}
                        <NumberField value={draft.crew_counts[org]?.[y] ?? years[y]} min={0} max={30} width="w-14" title={`${org} crews in ${y}`} onChange={(n) => setCount(org, y, n)} />
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[14px] font-semibold">Months with no outage work</span>
                <Button variant="ghost" className="!px-3 !py-1" onClick={() => setDraft({ ...draft, blackouts: [...draft.blackouts, { site: "*", months: [6, 7, 8], phase_kind: "energization" }] })}>
                  <Plus size={15} /> Add
                </Button>
              </div>
              {draft.blackouts.length === 0 && <p className="text-[13px] text-muted">None yet. Add one to keep outage work out of chosen months at a site.</p>}
              {draft.blackouts.map((b, i) => (
                <div key={i} className="mb-2 rounded-[16px] bg-soft px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <input value={b.site} onChange={(e) => setDraft({ ...draft, blackouts: draft.blackouts.map((x, j) => (j === i ? { ...x, site: e.target.value } : x)) })}
                      placeholder="Site name, or * for all" aria-label="Site"
                      className="min-w-0 flex-1 rounded-full bg-surface px-3 py-1 text-[13px] ring-1 ring-line focus:outline-none focus:ring-2 focus:ring-desc" />
                    <button aria-label="Remove" onClick={() => setDraft({ ...draft, blackouts: draft.blackouts.filter((_, j) => j !== i) })}
                      className="grid h-7 w-7 place-items-center rounded-full text-muted hover:bg-surface"><X size={15} /></button>
                  </div>
                  <div className="mt-2 flex gap-1">
                    {MONTHS.map((m, k) => {
                      const on = b.months.includes(k + 1);
                      return (
                        <button key={k} aria-pressed={on} onClick={() => setDraft({ ...draft, blackouts: draft.blackouts.map((x, j) => (j === i
                          ? { ...x, months: on ? x.months.filter((n) => n !== k + 1) : [...x.months, k + 1].sort((p, q) => p - q) } : x)) })}
                          className={`h-7 w-7 rounded-full text-[12px] font-semibold ${on ? "bg-ink text-white" : "bg-surface text-muted ring-1 ring-line"}`}>{m}</button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>

            <Button variant="primary" className="w-full" onClick={() => onSolve(draft)} disabled={solving}>{solving ? "Re-planning…" : "Re-plan with these rules"}</Button>
          </div>
        </Section>

        <Section title="Why each pair was or wasn't shared" count={decisions.length} defaultOpen>
          <div className="mb-2 flex flex-wrap gap-3 text-[12px] text-muted">
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-save" />shared</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-crew" />close enough, kept apart</span>
            <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-far" />too far by road</span>
          </div>
          <ul className="space-y-1">
            {decisions.map((d) => {
              const dot = d.decision === "share" ? "bg-save" : d.eligible ? "bg-crew" : "bg-far";
              return (
                <li key={d.opportunity_id}>
                  <button onClick={() => explain(d.opportunity_id)}
                    className={`w-full rounded-[16px] px-3 py-2.5 text-left transition ${d.opportunity_id === selectedId ? "bg-desc-soft" : "hover:bg-soft"}`}>
                    <div className="flex items-start gap-2.5">
                      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
                      <div className="min-w-0">
                        <div className="truncate text-[14px] font-semibold">{d.a} <span className="font-normal text-muted">and</span> {d.b}</div>
                        {d.decision === "share" && (d.shared?.length ?? 0) > 0 && <div className="text-[13px] font-semibold text-save">Shares {d.shared.join(", ")}{d.contractor ? ", plus one contractor" : ""}</div>}
                        <div className="mt-0.5 text-[13px] leading-snug text-muted">
                          {asking === d.opportunity_id ? "Checking what would happen if they shared…" : why[d.opportunity_id] || d.sentence}
                        </div>
                      </div>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </Section>
      </div>
    </div>
  );
}
