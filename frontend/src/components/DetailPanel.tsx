import { useEffect, useState } from "react";
import { api, type Assumption, type Job, type OpportunityDetail, type Savings } from "../api";
import { BASIS_LABEL, FLAG_LABEL, QUALITY_LABEL, STATUSES, miles, monthYear, pct, title, usd } from "../format";
import BriefModal from "./BriefModal";
import Outreach from "./Outreach";
import PlanDecision from "./PlanDecision";
import Vendors from "./Vendors";
import { TierChip } from "./OpportunityList";

type Props = {
  detail: OpportunityDetail;
  assumptions: Record<string, Assumption>;
  onClose: () => void;
  onStatus: (id: number, status: string) => void;
  onRefresh: () => void;
  overrides?: Values | null;
};

type Values = Record<string, { low: number; high: number }>;

export default function DetailPanel({ detail, assumptions, onClose, onStatus, onRefresh, overrides }: Props) {
  const [values, setValues] = useState<Values>({});
  const [savings, setSavings] = useState<Savings>(detail.savings);
  const [brief, setBrief] = useState<{ markdown: string; summary_source: string } | null>(null);
  const [drafting, setDrafting] = useState(false);

  const draftBrief = () => {
    setDrafting(true);
    api.brief(detail.id).then(setBrief).finally(() => setDrafting(false));
  };

  useEffect(() => {
    setValues(overrides ?? Object.fromEntries(Object.entries(assumptions).map(([k, a]) => [k, { low: a.low, high: a.high }])));
    if (overrides) api.savings(detail.id, overrides).then(setSavings);  // crewly what-if moves the sliders
    else setSavings(detail.savings);
  }, [detail, assumptions, overrides]);

  const change = (key: string, end: "low" | "high", v: number) => {
    const next = { ...values, [key]: { ...values[key], [end]: v } };
    setValues(next);
    api.savings(detail.id, next).then(setSavings);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <TierChip tier={detail.tier} />
          <span className="text-xs text-slate-500">score {detail.score.toFixed(2)}</span>
        </div>
        <button onClick={onClose} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
        <div className="space-y-3">
          <JobCard job={detail.a} />
          <JobCard job={detail.b} />
        </div>

        <section className="grid grid-cols-2 gap-2">
          <Metric label="Closest distance" value={miles(detail.distance_m)} />
          <Metric label="Center to center" value={miles(detail.center_distance_m)} />
          <Metric label="Drive time by road" warn={detail.drive_min != null && detail.drive_min > 45}
            value={detail.drive_min == null ? "unknown" : `${Math.round(detail.drive_min)} min · ${Math.round(detail.drive_km ?? 0)} km`} />
          <Metric label="Crew and yard sharing" warn={detail.drive_min != null && detail.drive_min > 45}
            value={detail.drive_min == null ? "not checked" : detail.drive_min > 45 ? "too far (over 45 min)" : "within 45 min"} />
          <Metric label="Build window overlap" value={pct(detail.time_overlap)} />
          <Metric label="In-service gap" value={detail.time_gap_days == null ? "n/a" : `${detail.time_gap_days} days`} />
          <Metric label="Hurricane risk (FEMA NRI)" value={`${Math.round(detail.risk * 100)} / 100`} />
          <Metric label="Social vulnerability (CDC SVI)" value={`${Math.round(detail.vulnerability * 100)}th pct`} />
          {detail.overlap_m > 0 && <Metric label="Parallel corridor" value={miles(detail.overlap_m)} />}
        </section>

        {detail.flags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {detail.flags.map((f) => <span key={f} className="rounded bg-orange-50 px-2 py-1 text-xs font-medium text-orange-700 ring-1 ring-orange-200">{FLAG_LABEL[f] ?? f}</span>)}
          </div>
        )}

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">What they could share</h3>
          <div className="flex flex-wrap gap-1.5">
            {detail.shareable.map((s) => <span key={s} className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">{s}</span>)}
            {detail.shareable.length === 0 && <span className="text-xs text-slate-500">Nothing: the sites are more than a 45 minute drive apart.</span>}
          </div>
        </section>

        {detail.horizon === "long" && <PlanDecision opportunityId={detail.id} />}
        <Vendors opportunityId={detail.id} />

        <section className="rounded-lg bg-emerald-50 p-3 ring-1 ring-emerald-200">
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Estimated savings</div>
          <div className="mt-1 text-2xl font-semibold text-emerald-900">{usd(savings.low)} – {usd(savings.high)}</div>
          <table className="mt-2 w-full text-xs text-emerald-900">
            <tbody>
              {Object.entries(savings.items).map(([k, v]) => (
                <tr key={k}><td className="py-0.5">{k}</td><td className="text-right">{usd(v.low)} – {usd(v.high)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-emerald-800/80">Assumes both jobs are scheduled together. Ranges come from the assumptions below, not from AI.</p>
        </section>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Assumptions</h3>
          <div className="space-y-3">
            {Object.entries(assumptions).map(([key, a]) => values[key] && (
              <div key={key}>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium text-slate-700">{a.label}</span>
                  <span className="text-slate-500">
                    {values[key].low.toLocaleString()}–{values[key].high.toLocaleString()} {a.unit}
                    {!a.verified && <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] font-semibold text-amber-800">placeholder</span>}
                  </span>
                </div>
                <div className="mt-1 flex gap-2">
                  {(["low", "high"] as const).map((end) => (
                    <input key={end} type="range" className="w-full accent-emerald-600" min={0} max={a.high * 3} step={a.high / 50}
                      value={values[key][end]} onChange={(e) => change(key, end, Number(e.target.value))} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <button onClick={draftBrief} disabled={drafting}
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60">
          {drafting ? "Drafting brief…" : "Draft coordination brief"}
        </button>

        <Outreach opportunityId={detail.id} onStatus={onRefresh} />

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Coordination status</h3>
          <select value={detail.status} onChange={(e) => onStatus(detail.id, e.target.value)}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
            {STATUSES.map((s) => <option key={s} value={s}>{title(s)}</option>)}
          </select>
        </section>
      </div>
      {brief && <BriefModal markdown={brief.markdown} source={brief.summary_source} onClose={() => setBrief(null)} />}
    </div>
  );
}

function Metric({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`text-sm font-semibold ${warn ? "text-rose-600" : ""}`}>{value}</div>
    </div>
  );
}

function JobCard({ job }: { job: Job }) {
  const approx = job.confidence < 0.7 || ["straight_line", "partial_point", "manual"].includes(job.geom_quality);
  return (
    <div className="rounded-lg border border-slate-200 p-3" style={{ borderLeft: `4px solid ${job.color}` }}>
      <div className="text-[11px] font-medium" style={{ color: job.color }}>{job.org_name}</div>
      <div className="text-sm font-semibold leading-5">{job.name}</div>
      {job.phase && <div className="mt-0.5 text-xs font-medium text-slate-700">Phase: {job.phase} <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500">derived</span></div>}
      <div className="mt-1 text-xs text-slate-600">
        {title(job.job_type)}{job.voltage_kv ? ` · ${job.voltage_kv} kV` : ""} · {monthYear(job.start_at)} → {monthYear(job.end_at)}
      </div>
      <div className="mt-0.5 text-[11px] text-slate-400">{BASIS_LABEL[job.window_basis] ?? job.window_basis}</div>
      {job.history?.map((h) => (
        <div key={h.observed_at} className="mt-0.5 text-[11px] text-orange-700">
          Earlier plan ({monthYear(h.observed_at)}): in service {monthYear(h.end_at)}, now {monthYear(job.end_at)}
        </div>
      ))}
      {job.description && <p className="mt-2 line-clamp-3 text-xs text-slate-600">{job.description}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className={`rounded px-1.5 py-0.5 ${approx ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>
          {QUALITY_LABEL[job.geom_quality] ?? job.geom_quality}
        </span>
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">location {pct(job.confidence)}</span>
        <span className="text-slate-400">{job.source_title}, p.{job.source_page}</span>
      </div>
    </div>
  );
}
