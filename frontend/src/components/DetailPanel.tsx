import { FileText, Info, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Assumption, type Job, type OpportunityDetail, type Savings } from "../api";
import { BASIS_LABEL, FLAG_LABEL, QUALITY_LABEL, STATUSES, TIER_HINT, miles, monthYear, pct, title, tooFar, usd } from "../format";
import BriefModal from "./BriefModal";
import Outreach from "./Outreach";
import PlanDecision from "./PlanDecision";
import { Button, Chip, CloseButton, PairBubble, Stat, TierPill } from "./ui";
import { Disclosure, inputClass } from "./ui-extra";
import Vendors from "./Vendors";

type Sourced = Assumption & { url?: string | null; page?: string; note?: string; scope?: string };  // cited cost ranges from /api/assumptions

type Props = {
  detail: OpportunityDetail;
  assumptions: Record<string, Assumption>;
  onClose: () => void;
  onStatus: (id: number, status: string) => void;
  onRefresh: () => void;
  overrides?: Values | null;
};

type Values = Record<string, { low: number; high: number }>;
type Part = "projects" | "why" | "plan" | "costs" | "reach" | "status";

export default function DetailPanel({ detail, assumptions, onClose, onStatus, onRefresh, overrides }: Props) {
  const [values, setValues] = useState<Values>({});
  const [savings, setSavings] = useState<Savings>(detail.savings);
  const [brief, setBrief] = useState<{ markdown: string; summary_source: string } | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [open, setOpen] = useState<Partial<Record<Part, boolean>>>({ projects: true });
  const far = tooFar(detail.drive_min);

  const draftBrief = () => {
    setDrafting(true);
    api.brief(detail.id).then(setBrief).finally(() => setDrafting(false));
  };

  useEffect(() => {
    setValues(overrides ?? Object.fromEntries(Object.entries(assumptions).map(([k, a]) => [k, { low: a.low, high: a.high }])));
    if (overrides) {
      api.savings(detail.id, overrides).then(setSavings);  // crewly what-if moves the sliders
      setOpen((o) => ({ ...o, costs: true }));
    } else setSavings(detail.savings);
  }, [detail, assumptions, overrides]);

  const change = (key: string, end: "low" | "high", v: number) => {
    const next = { ...values, [key]: { ...values[key], [end]: v } };
    setValues(next);
    api.savings(detail.id, next).then(setSavings);
  };

  const toggle = (p: Part) => setOpen((o) => ({ ...o, [p]: !o[p] }));
  const startOutreach = () => {
    setOpen((o) => ({ ...o, reach: true }));
    requestAnimationFrame(() => document.getElementById(`reach-${detail.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const share = detail.shareable;
  const sourced = Object.entries(assumptions as Record<string, Sourced>).filter(([, a]) => a.scope !== "storm");  // storm crew costs belong to the storm plan
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-5 pt-4">
        <TierPill tier={detail.tier} far={far} />
        <CloseButton onClick={onClose} />
      </div>

      <div className="thin-scroll min-h-0 flex-1 overflow-y-auto px-5 pb-5">
        <div className="mt-3"><PairBubble a={detail.a.name} b={detail.b.name} /></div>
        <p className="mt-2 text-[13px] text-muted">{detail.a.org_name} and {detail.b.org_name}</p>

        {far ? (
          <div className="mt-5 rounded-[20px] bg-soft px-5 py-4">
            <div className="display text-[24px] font-semibold text-muted">Too far by road</div>
            <p className="mt-1 text-[14px] text-muted">
              The sites are {Math.round(detail.drive_min ?? 0)} minutes apart by road, over the 45 minute limit for sharing crews or a yard.
            </p>
          </div>
        ) : (
          <div className="mt-5 rounded-[20px] bg-save-soft px-5 py-4">
            <div className="display text-[30px] font-semibold leading-tight text-save">{usd(savings.low)} to {usd(savings.high)}</div>
            <p className="mt-1 text-[14px] text-ink/80">Could be saved if the two jobs are scheduled together.</p>
          </div>
        )}

        <div className="mt-3 grid grid-cols-3 gap-2">
          <Stat label="Apart" value={miles(detail.distance_m)} tone={far ? "warn" : undefined}
            hint={detail.drive_min == null ? "drive time unknown" : `${Math.round(detail.drive_min)} min by road`} />
          <Stat label="Same time" value={pct(detail.time_overlap)} hint="of the build window" />
          <Stat label="Could share" value={share.length ? capital(share[0]) : "Nothing"} hint={share.length > 1 ? `and ${share.length - 1} more` : undefined} />
        </div>

        <p className="mt-4 flex gap-2 text-[14px] leading-relaxed text-muted">
          <Info size={17} className="mt-0.5 shrink-0 text-faint" />
          <span>{far ? "Crews and yards only count when the sites are within a 45 minute drive." : TIER_HINT[detail.tier]}</span>
        </p>

        <div className="mt-4">
          <Disclosure title="The two projects" open={!!open.projects} onToggle={() => toggle("projects")}>
            <div className="space-y-2.5">
              <JobCard job={detail.a} />
              <JobCard job={detail.b} />
            </div>
          </Disclosure>

          <Disclosure title="Why it ranks here" open={!!open.why} onToggle={() => toggle("why")}>
            <dl className="divide-y divide-line rounded-2xl bg-soft px-4">
              <Row label="Hurricane risk (FEMA)" value={`${Math.round(detail.risk * 100)} out of 100`} />
              <Row label="Community vulnerability (CDC)" value={`${ordinal(Math.round(detail.vulnerability * 100))} percentile`} />
              <Row label="Finish dates apart" value={detail.time_gap_days == null ? "Unknown" : `${detail.time_gap_days} days`} />
              <Row label="Center to center" value={miles(detail.center_distance_m)} />
              {detail.overlap_m > 0 && <Row label="Running side by side" value={miles(detail.overlap_m)} />}
              <Row label="Ranking score" value={detail.score.toFixed(2)} />
            </dl>
            {detail.flags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {detail.flags.map((f) => <Chip key={f} tone="warn">{FLAG_LABEL[f] ?? f}</Chip>)}
              </div>
            )}
            {share.length > 0 && (
              <p className="mt-3 text-[14px] text-muted">They could share {share.join(", ")}.</p>
            )}
          </Disclosure>

          {detail.horizon === "long" && (
            <Disclosure title="Joint plan decision" open={!!open.plan} onToggle={() => toggle("plan")}>
              <PlanDecision opportunityId={detail.id} />
            </Disclosure>
          )}

          <Disclosure title="Cost assumptions" open={!!open.costs} onToggle={() => toggle("costs")}>
            <p className="text-[13px] text-muted">Every dollar figure comes from these ranges, not from AI. Each range cites its document. Drag to see how the savings change.</p>
            {Object.keys(savings.items).length > 0 && (
              <dl className="mt-3 divide-y divide-line rounded-2xl bg-save-soft/60 px-4">
                {Object.entries(savings.items).map(([k, v]) => <Row key={k} label={capital(k)} value={`${usd(v.low)} to ${usd(v.high)}`} />)}
              </dl>
            )}
            <div className="mt-4 space-y-4">
              {sourced.map(([key, a]) => values[key] && (
                <div key={key}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-[14px] font-semibold">
                      {a.label}
                      {!a.verified && <Chip tone="warn">estimate</Chip>}
                    </span>
                    <span className="text-[13px] text-muted">{values[key].low.toLocaleString()} to {values[key].high.toLocaleString()} {a.unit}</span>
                  </div>
                  {a.note && <p className="mt-0.5 text-[12px] leading-snug text-faint">{a.note}</p>}
                  {a.url
                    ? <a href={a.url} target="_blank" rel="noopener noreferrer" className="mt-0.5 inline-block text-[12px] font-semibold text-desc hover:underline"
                        title={a.source}>Source: {a.source.length > 60 ? `${a.source.slice(0, 58)}…` : a.source}{a.page ? `, p. ${a.page}` : ""}</a>
                    : <span className="mt-0.5 block text-[12px] text-faint">Source: {a.source}</span>}
                  <div className="mt-1.5 grid grid-cols-2 gap-3">
                    {(["low", "high"] as const).map((end) => (
                      <label key={end} className="text-[12px] text-faint">
                        {end === "low" ? "Low" : "High"}
                        <input type="range" className="mt-0.5 w-full accent-[#12a36b]" min={0} max={a.high * 3} step={a.high / 50}
                          value={values[key][end]} onChange={(e) => change(key, end, Number(e.target.value))} />
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Disclosure>

          <Disclosure id={`reach-${detail.id}`} title="Reach out" open={!!open.reach} onToggle={() => toggle("reach")}>
            <div className="space-y-5">
              <Outreach opportunityId={detail.id} onStatus={onRefresh} />
              <Vendors opportunityId={detail.id} />
            </div>
          </Disclosure>

          <Disclosure title="Status" count={title(detail.status)} open={!!open.status} onToggle={() => toggle("status")}>
            <select value={detail.status} onChange={(e) => onStatus(detail.id, e.target.value)} className={inputClass} aria-label="Coordination status">
              {STATUSES.map((s) => <option key={s} value={s}>{title(s)}</option>)}
            </select>
          </Disclosure>
        </div>
      </div>

      <div className="flex gap-2 border-t border-line bg-surface px-5 py-3">
        <Button variant="primary" className="flex-1" onClick={draftBrief} disabled={drafting}>
          <FileText size={16} />{drafting ? "Writing the brief…" : "Write a brief"}
        </Button>
        <Button className="flex-1" onClick={startOutreach}><Send size={16} />Start outreach</Button>
      </div>
      {brief && <BriefModal markdown={brief.markdown} source={brief.summary_source} onClose={() => setBrief(null)} />}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 text-[14px]">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-semibold">{value}</dd>
    </div>
  );
}

function JobCard({ job }: { job: Job }) {
  const approx = job.confidence < 0.7 || ["straight_line", "partial_point", "manual"].includes(job.geom_quality);
  return (
    <div className="rounded-2xl bg-soft py-3 pl-4 pr-3" style={{ boxShadow: `inset 4px 0 0 ${job.color}` }}>
      <div className="text-[13px] font-semibold" style={{ color: job.color }}>{job.org_name}</div>
      <div className="mt-0.5 text-[15px] font-semibold leading-snug">{job.name}</div>
      {job.phase && <div className="mt-1 text-[13px] text-muted">Phase: {job.phase} (estimated from the project window)</div>}
      <div className="mt-1.5 text-[14px]">
        {capital(title(job.job_type))}{job.voltage_kv ? `, ${job.voltage_kv} kV` : ""}, {monthYear(job.start_at)} to {monthYear(job.end_at)}
      </div>
      <div className="text-[13px] text-faint">{capital(BASIS_LABEL[job.window_basis] ?? job.window_basis)}</div>
      {job.history?.map((h) => (
        <div key={h.observed_at} className="mt-1 text-[13px] text-warn">
          The {monthYear(h.observed_at)} plan finished in {monthYear(h.end_at)}; now {monthYear(job.end_at)}
        </div>
      ))}
      {job.description && <p className="mt-2 line-clamp-3 text-[13px] leading-relaxed text-muted">{job.description}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Chip tone={approx ? "warn" : "plain"}>{capital(QUALITY_LABEL[job.geom_quality] ?? job.geom_quality)}</Chip>
        <Chip>{pct(job.confidence)} sure of the location</Chip>
      </div>
      <div className="mt-2 text-[12px] text-faint">Source: {job.source_title}, page {job.source_page}</div>
    </div>
  );
}

function capital(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

function ordinal(n: number) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${s}`;
}
