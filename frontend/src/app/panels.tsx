import { ArrowDownLeft, ArrowUpRight, CalendarClock, Check, ChevronDown, ChevronLeft, ChevronRight, Clock3, CloudSun, Coins, Handshake, MapPin, Newspaper, RefreshCw, Send, Telescope, Users, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import type { Savings } from "../api";
import {
  TIER_LABEL, company, partnerOf, ago, api, miles, month, requests as requestsApi, usd,
  type CollabRequest, type Feasibility, type FeasibilityFactor, type Jobs, type Me, type Overlap, type OverlapDetail, type Verdict,
} from "./data";
import { say } from "./mascot";
import { Chip as UiChip, type ChipTone } from "./ui";
import { NotesBlock } from "./workspace/Cards";

export function PanelHeader({ title, sub, onBack, right }: { title: string; sub?: React.ReactNode; onBack?: () => void; right?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 pb-3">
      {onBack && (
        <button onClick={onBack} aria-label="Back" className="-ml-1 mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full border-2 border-pen bg-white hover:bg-grape-soft">
          <ChevronLeft size={18} strokeWidth={2.5} />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <h2 className="font-logo text-xl font-semibold leading-tight">{title}</h2>
        {sub && <div className="mt-0.5 text-sm text-muted">{sub}</div>}
      </div>
      {right}
    </div>
  );
}

export function TierChip({ tier }: { tier: string }) {
  const t = TIER_LABEL[tier] ?? { label: tier, color: "#888" };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold" style={{ background: `${t.color}22`, color: "#1b2447" }}>
      <span className="h-2 w-2 rounded-full" style={{ background: t.color }} />{t.label}
    </span>
  );
}

const STATUS = {
  pending: { label: "Pending", cls: "bg-crew-soft text-[#8a5a00]" },
  approved: { label: "Approved", cls: "bg-save-soft text-save" },
  declined: { label: "Declined", cls: "bg-gpc-soft text-[#c23b3b]" },
};

export function StatusChip({ status }: { status: CollabRequest["status"] }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS[status].cls}`}>{STATUS[status].label}</span>;
}

export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const count = (n: number) => n.toLocaleString("en-US");

export const sentence = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);  // "land tier: ..." reads as "Land tier: ..."
export type Tone = "neutral" | "good" | "warn" | "bad" | "info";
const TONE: Record<Tone, ChipTone> = { neutral: "neutral", good: "good", warn: "amber", bad: "danger", info: "info" };  // panel tones on the chat's chip

// one chip style for every label in the app: status, verdict, impact, confidence (the same component the chat cards use)
export function Chip({ tone = "neutral", icon, title, children }: { tone?: Tone; icon?: React.ReactNode; title?: string; children: React.ReactNode }) {
  return <UiChip tone={TONE[tone]} icon={icon} title={title}>{children}</UiChip>;
}

// a confidence as a labelled chip with a small meter, toned by band
export function ConfidenceChip({ value, label = "Confidence" }: { value: number; label?: string }) {
  const tone: Tone = value >= 0.7 ? "good" : value >= 0.4 ? "neutral" : "warn";
  return (
    <Chip tone={tone} title={`${label} ${pct(value)}`}>
      {label} <span className="tabular-nums">{pct(value)}</span>
      <span className="ml-0.5 inline-block h-1.5 w-7 overflow-hidden rounded-full bg-white/70"><span className="block h-full rounded-full bg-current opacity-70" style={{ width: pct(value) }} /></span>
    </Chip>
  );
}

// label and value pairs, aligned in two columns
export function Meta({ rows }: { rows: [string, React.ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {shown.map(([k, v]) => <Fragment key={k}><dt className="font-semibold text-faint">{k}</dt><dd className="min-w-0 text-ink">{v}</dd></Fragment>)}
    </dl>
  );
}

// the row every list is made of: a lead mark, a title, a meta line and an optional chip on the right
export function ListRow({ lead, title, sub, right, active, onClick, className = "" }: {
  lead?: React.ReactNode; title: React.ReactNode; sub?: React.ReactNode; right?: React.ReactNode; active?: boolean; onClick: () => void; className?: string;
}) {
  return (
    <button onClick={onClick} className={`card-lift flex w-full items-start gap-2.5 px-3 py-2.5 text-left ${active ? "is-active" : ""} ${className}`}>
      {lead && <span className="mt-0.5 shrink-0">{lead}</span>}
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 block text-sm font-semibold leading-snug">{title}</span>
        {sub && <span className="mt-0.5 line-clamp-2 block text-xs leading-snug text-muted">{sub}</span>}
      </span>
      {right && <span className="shrink-0">{right}</span>}
    </button>
  );
}

// a round mark for a list row: a small dot, or an icon on a coloured disc
export const Dot = ({ color, dim }: { color: string; dim?: boolean }) => <span className="mt-1.5 block h-2.5 w-2.5 rounded-full" style={{ background: color, opacity: dim ? 0.45 : 1 }} />;
export const Disc = ({ color, children }: { color: string; children: React.ReactNode }) => <span className="grid h-7 w-7 place-items-center rounded-full text-white" style={{ background: color }}>{children}</span>;

// why an overlap has no savings: crews can only be shared when both builds run at once and within a 45 min drive
export function noSavings(o: Overlap | OverlapDetail) {
  if (o.savings_high > 0) return null;
  if (o.time_overlap === 0) return { short: "different build years", long: `These builds don't run at the same time${o.time_gap_days ? ` (in service about ${Math.round(o.time_gap_days / 30)} months apart)` : ""}, so crews and equipment can't be shared.` };
  if (o.drive_min != null && o.drive_min > 45) return { short: "over 45 min drive", long: `The sites are ${Math.round(o.drive_min)} minutes apart by road, too far to share crews and yards day to day.` };
  return { short: "no shared savings", long: "Nothing here can be shared at the same time." };
}

export const latestFor = (reqs: CollabRequest[], id: number) => reqs.find((r) => r.opportunity_id === id);  // list is newest first

// ours first: every overlap is shown from the logged-in company's side
export function sides(me: Me, o: Overlap | OverlapDetail) {
  const a = o.a_org === me.company;
  return {
    ours: { name: a ? o.a_name : o.b_name, start: a ? o.a_start : o.b_start, end: a ? o.a_end : o.b_end, job: a ? o.job_a : o.job_b },
    theirs: { name: a ? o.b_name : o.a_name, start: a ? o.b_start : o.a_start, end: a ? o.b_end : o.a_end, job: a ? o.job_b : o.job_a },
  };
}

export function ProjectList({ me, projects, onPick }: { me: Me; projects: Jobs | null; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const rows = useMemo(() => (projects?.features ?? []).map((f) => f.properties)
    .filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase())), [projects, q]);
  return (
    <>
      <PanelHeader title="Your projects" sub={projects ? `${projects.features.length} planned by ${me.name}` : "Loading..."} />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search projects"
        className="mb-2 rounded-full border-2 border-line bg-white px-3.5 py-1.5 text-sm outline-none focus:border-pen" />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto px-0.5 pb-1 pr-2">
        {rows.map((p) => (
          <ListRow key={p.id} onClick={() => onPick(p.id)} lead={<span className="block h-8 w-1 rounded-full" style={{ background: me.color }} />} title={p.name}
            sub={[p.voltage_kv && `${p.voltage_kv} kV`, `${month(p.start_at)} to ${month(p.end_at)}`].filter(Boolean).join(" · ")} />
        ))}
        {!rows.length && <p className="px-2 py-6 text-center text-sm text-muted">No projects match.</p>}
      </div>
    </>
  );
}

export function OverlapCard({ me, o, req, active, struck, onClick }: { me: Me; o: Overlap; req?: CollabRequest; active?: boolean; struck?: boolean; onClick: () => void }) {
  const s = sides(me, o);
  const none = noSavings(o);
  return (
    <button onClick={onClick} aria-pressed={active}
      className={`card-lift w-full px-3 py-2.5 text-left ${active ? "is-active" : ""} ${struck ? "line-through opacity-50" : ""}`}>
      <div className="mb-1 flex items-center gap-2">
        <TierChip tier={o.tier} /><span className="text-xs font-semibold tabular-nums text-faint">#{o.id}</span>
        <span className="flex min-w-0 items-center gap-1 truncate text-xs font-semibold text-muted">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: company(partnerOf(me, o)).color }} />{company(partnerOf(me, o)).short}
        </span>
        <span className="flex-1" />{req && <StatusChip status={req.status} />}
      </div>
      <div className="line-clamp-2 text-sm font-semibold leading-snug">{s.ours.name}</div>
      <div className="line-clamp-1 text-xs text-muted">with {s.theirs.name}</div>
      <div className="mt-1.5 flex items-center gap-1.5 text-xs text-muted">
        <span className="tabular-nums">{miles(o.distance_m)} apart</span>
        {o.drive_min != null && <><span className="text-faint">·</span><span className="tabular-nums">{Math.round(o.drive_min)} min drive</span></>}
        <span className="flex-1" />
        {none ? <span className="text-faint">{none.short}</span> : <span className="font-semibold tabular-nums text-save">{usd(o.savings_low)} to {usd(o.savings_high)}</span>}
      </div>
    </button>
  );
}

export function OverlapList({ me, overlaps, requests, selected, focused, partners, partner, onPartner, onOpen, onClearFocus, struck }: {
  me: Me; overlaps: Overlap[]; requests: CollabRequest[]; selected: number | null; focused: boolean;
  partners: { id: string; n: number }[]; partner: string | null; onPartner: (id: string | null) => void;
  onOpen: (id: number) => void; onClearFocus: () => void; struck?: Set<string>;  // neighbors an experiment excludes
}) {
  const total = partners.reduce((a, p) => a + p.n, 0);
  return (
    <>
      <PanelHeader title={`${overlaps.length} overlap${overlaps.length === 1 ? "" : "s"}`}
        sub={partner ? `with ${company(partner).name}` : partners.length === 1 ? `with ${company(partners[0].id).name}` : "with neighboring utilities"}
        right={focused ? (
          <button onClick={onClearFocus} className="mt-1 flex items-center gap-1 rounded-full bg-grape-soft px-2.5 py-1 text-xs font-semibold text-grape hover:bg-grape hover:text-white">
            From chat <X size={13} />
          </button>
        ) : undefined} />
      {partners.length > 1 && (
        <div className="thin-scroll -mx-1 mb-2 flex gap-1.5 overflow-x-auto px-1 pb-1">
          <button onClick={() => onPartner(null)} className={`shrink-0 rounded-full border-2 px-2.5 py-0.5 text-xs font-semibold ${partner ? "border-line text-muted hover:border-pen" : "border-pen bg-grape-soft"}`}>
            All {total}
          </button>
          {partners.map((p) => (
            <button key={p.id} onClick={() => onPartner(p.id === partner ? null : p.id)}
              className={`flex shrink-0 items-center gap-1.5 rounded-full border-2 px-2.5 py-0.5 text-xs font-semibold ${p.id === partner ? "border-pen bg-grape-soft" : "border-line text-muted hover:border-pen"}`}>
              <span className="h-2 w-2 rounded-full" style={{ background: company(p.id).color }} />{company(p.id).short} {p.n}
            </button>
          ))}
        </div>
      )}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto px-0.5 pb-1 pr-2">
        {overlaps.map((o) => <OverlapCard key={o.id} me={me} o={o} req={latestFor(requests, o.id)} active={o.id === selected} onClick={() => onOpen(o.id)} struck={struck?.has(partnerOf(me, o))} />)}
        {!overlaps.length && <p className="px-2 py-6 text-center text-sm text-muted">No overlaps match.</p>}
      </div>
    </>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card-still px-2.5 py-2" title={hint}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">{label}</div>
      <div className="font-logo text-base font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function ProjectBlock({ who, color, name, start, end, extra }: { who: string; color: string; name: string; start: string; end: string; extra?: string }) {
  return (
    <div className="card-still px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs font-semibold" style={{ color }}><span className="h-2 w-2 rounded-full" style={{ background: color }} />{who}</div>
      <div className="mt-0.5 text-sm font-semibold leading-snug">{name}</div>
      <div className="text-xs text-muted">{month(start)} to {month(end)}{extra ? ` · ${extra}` : ""}</div>
    </div>
  );
}

type WeatherCost = { cost?: { total: { low: number; high: number } }; coordination?: { savings: { low: number; high: number } } };
const THIS_MONTH = new Date().getMonth() + 1;
const MONTH_NAME = new Date().toLocaleDateString("en-US", { month: "long" });

const METHOD_DOC = "https://github.com/iviraa/opencrew/blob/main/docs/cost-savings-model.md";
const CAT_TINT: Record<string, string> = {  // one colour per cost type, matching config.CATEGORIES
  labor: "#7c4dff", equipment: "#00b8a9", travel: "#ffb020", time: "#ff4fa3", land: "#43aa8b", overhead: "#577590",
};

const range = (lo: number, hi: number) => <>{usd(lo)}<span className="font-normal text-faint"> to </span>{usd(hi)}</>;

// where the headline figure comes from: one row per cost type, opening to the lines and the published price behind each
function SavingsTable({ s }: { s: Savings }) {
  const [open, setOpen] = useState<string | null>(null);
  const cats = s.categories ?? [];
  const lines = s.lines ?? [];
  if (!cats.length) return null;
  const max = Math.max(...cats.map((c) => c.high), 1);
  return (
    <table className="mt-2.5 w-full border-collapse text-xs">
      <caption className="sr-only">Where the estimated savings come from</caption>
      <thead>
        <tr className="border-b-2 border-line text-[10px] uppercase tracking-wide text-faint">
          <th scope="col" className="pb-1 text-left font-semibold">Where it comes from</th>
          <th scope="col" className="pb-1 text-right font-semibold">Saving</th>
        </tr>
      </thead>
      <tbody>
        {cats.map((c) => {
          const shown = open === c.key;
          return (
            <Fragment key={c.key}>
              <tr className="border-b border-line/60 align-top">
                <th scope="row" className="py-1.5 pr-2 text-left font-semibold">
                  <button onClick={() => setOpen(shown ? null : c.key)} aria-expanded={shown} title={c.hint}
                    className="flex w-full items-center gap-1 text-left hover:text-grape">
                    <ChevronRight size={12} strokeWidth={3} className={`shrink-0 transition ${shown ? "rotate-90" : ""}`} />
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: CAT_TINT[c.key] ?? "#888" }} />
                    {c.label}
                  </button>
                  <span className="mt-1 block h-1.5 rounded-full bg-white">
                    <span className="block h-full rounded-full" style={{ width: `${(c.high / max) * 100}%`, background: CAT_TINT[c.key] ?? "#888" }} />
                  </span>
                </th>
                <td className="py-1.5 text-right font-semibold tabular-nums">{range(c.low, c.high)}</td>
              </tr>
              {shown && lines.filter((l) => l.category === c.key).map((l) => (
                <tr key={l.name} className="border-b border-line/40 bg-white/60 align-top">
                  <td className="py-1.5 pl-4.75 pr-2">
                    <span className="font-semibold">{l.name}</span>
                    <span className="mt-0.5 block text-[11px] leading-snug text-muted">{[l.qty, l.over].filter(Boolean).join(" · ")}</span>
                    <span className="block text-[11px] leading-snug text-faint">{l.basis}</span>
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{range(l.low, l.high)}</td>
                </tr>
              ))}
            </Fragment>
          );
        })}
      </tbody>
      <tfoot>
        <tr className="border-t-2 border-pen">
          <th scope="row" className="pt-1.5 text-left font-semibold">Total</th>
          <td className="pt-1.5 text-right font-semibold tabular-nums text-save">{range(s.low, s.high)}</td>
        </tr>
      </tfoot>
    </table>
  );
}

// the scaling and the sanity check under the table, in the same order the backend applies them
function savingsNote(s: Savings) {
  const f = s.factors;
  if (!f) return null;
  const bits = [`${Math.round(f.same_time * 100)}% time overlap`, `${Math.round(f.drive * 100)}% drive factor`];
  if (f.kv) bits.push(`${f.kv} kV job size`);
  if (f.project_scale != null && f.project_scale < 1) bits.push(`setup sized to ${Math.round(f.project_scale * 100)}% of a $10M project`);
  const share = s.share_of_budget;
  return (
    <>Scaled by {bits.join(", ")}.{f.shared_days ? ` ${f.shared_days} days of shared build window.` : ""}
      {share ? ` That is ${(share.low * 100).toFixed(1)}% to ${(share.high * 100).toFixed(1)}% of the smaller project's budget.` : ""}</>
  );
}

const VERDICT = {
  strong: { label: "Strong", cls: "bg-save-soft text-save" },
  possible: { label: "Possible", cls: "bg-crew-soft text-[#8a5a00]" },
  unlikely: { label: "Unlikely", cls: "bg-gpc-soft text-[#c23b3b]" },
  unknown: { label: "Unknown", cls: "bg-soft text-muted" },
};
const FACTOR_ICON: Record<string, typeof MapPin> = {
  location: MapPin, timing: CalendarClock, cost: Coins, forecast: CloudSun, news: Newspaper, counterparty: Users, future: Telescope,
};
const said = new Set<number>();  // the beaver comments on each assessment once

export function VerdictChip({ verdict, score }: { verdict: Verdict; score?: number | null }) {
  const v = VERDICT[verdict] ?? VERDICT.unknown;
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${v.cls}`}>{v.label}{score != null && <span className="tabular-nums opacity-80">{Math.round(score * 100)}</span>}</span>;
}

function FactorCard({ f }: { f: FeasibilityFactor }) {
  const [open, setOpen] = useState(false);
  const Icon = FACTOR_ICON[f.factor] ?? Telescope;
  const more = f.conditions.length > 0 || f.evidence.length > 2;
  const line = (t: string) => sentence(t) + (/[.!?]$/.test(t) ? "" : ".");  // evidence comes as lowercase fragments
  return (
    <div className="card-still px-2.5 py-2">
      <button onClick={() => more && setOpen(!open)} aria-expanded={more ? open : undefined} className="flex w-full items-center gap-2 text-left">
        <Icon size={15} className="shrink-0 text-muted" />
        <span className="flex-1 text-sm font-semibold">{f.label}</span>
        <VerdictChip verdict={f.verdict} />
        {more && <ChevronDown size={14} className={`text-faint transition ${open ? "rotate-180" : ""}`} />}
      </button>
      <ul className="mt-1 flex flex-col gap-0.5 text-xs leading-snug text-muted">{(open ? f.evidence : f.evidence.slice(0, 2)).map((e, i) => <li key={i}>{line(e)}</li>)}</ul>
      {open && f.conditions.length > 0 && (
        <div className="mt-1.5 rounded-lg bg-soft px-2 py-1.5 text-xs">
          <div className="font-semibold text-muted">What would make it work</div>
          <ul className="mt-0.5 list-disc pl-4">{f.conditions.map((c, i) => <li key={i}>{line(c)}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function ShiftStrip({ f }: { f: FeasibilityFactor }) {
  const opts = (f.options ?? []).filter((o) => o.overlap_delta > 0.05 || (o.weather_cost_delta && o.weather_cost_delta.high < -500)).slice(0, 4);
  if (!opts.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {opts.map((o) => (
        <span key={o.months} className="rounded-full bg-soft px-2 py-0.5 text-xs" title="If our build window moved">
          Shift ours {o.months > 0 ? "+" : ""}{o.months} mo: {Math.round(o.overlap * 100)}% overlap
          {o.weather_cost_delta && o.weather_cost_delta.high !== 0 && `, weather ${o.weather_cost_delta.high < 0 ? "-" : "+"}${usd(Math.abs(o.weather_cost_delta.high))}`}
        </span>
      ))}
    </div>
  );
}

export function FeasibilitySection({ id, partner }: { id: number; partner: string }) {
  const [fz, setFz] = useState<Feasibility | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = (refresh: boolean) => {
    setBusy(true); setErr(null);
    api.get<Feasibility>(`/api/app/feasibility/${id}${refresh ? "?refresh=1" : ""}`).then((r) => {
      setFz(r);
      if (!said.has(id)) {
        said.add(id);
        const lead = r.factors.find((f) => f.verdict === (r.verdict === "unlikely" ? "unlikely" : "strong"))?.evidence[0];
        say(`Overlap #${id} looks ${VERDICT[r.verdict].label.toLowerCase()}${lead ? `: ${lead}` : ""}.`, r.verdict === "unlikely" ? "sad" : r.verdict === "strong" ? "happy" : "nod");
      }
    }).catch((e) => setErr(String(e.message ?? e))).finally(() => setBusy(false));
  };
  useEffect(() => { setFz(null); load(false); }, [id]);  // eslint-disable-line react-hooks/exhaustive-deps
  const timing = fz?.factors.find((f) => f.factor === "timing");
  return (
    <section className="card-still px-3 py-3">
      <div className="flex items-center gap-2">
        <h3 className="flex-1 text-sm font-semibold text-muted">Feasibility</h3>
        {fz && <VerdictChip verdict={fz.verdict} score={fz.score} />}
        <button onClick={() => load(true)} disabled={busy} aria-label="Re-assess" title="Re-assess" className="grid h-7 w-7 place-items-center rounded-full border-2 border-line bg-white text-muted hover:border-pen disabled:opacity-50">
          <RefreshCw size={13} className={busy ? "animate-spin" : ""} />
        </button>
      </div>
      {!fz && !err && <p className="mt-1 text-xs text-muted"><span className="dots">Assessing location, timing, cost, forecast and news</span></p>}
      {err && <p className="mt-1 text-xs text-warn">{err}</p>}
      {fz && (
        <>
          <p className="mt-1.5 text-sm leading-snug">{fz.narrative}</p>
          <div className="mt-2 flex flex-col gap-1.5">{fz.factors.map((f) => <FactorCard key={f.factor} f={f} />)}</div>
          {timing && <div className="mt-2"><ShiftStrip f={timing} /></div>}
          <p className="mt-2 text-[11px] leading-snug text-faint">An assessment of the pair with {partner}, from the app's own numbers. It is not a work order.</p>
        </>
      )}
    </section>
  );
}

export function OverlapDetailPanel({ me, id, requests, onBack, onSent, onOpenRequest, onHazards, onNotebook }: {
  me: Me; id: number; requests: CollabRequest[]; onBack: () => void; onSent: (r: CollabRequest) => void; onOpenRequest: (id: number) => void;
  onNotebook?: () => void; onHazards?: (id: number, month: number) => void;
}) {
  const [d, setD] = useState<OverlapDetail | null>(null);
  const [wx, setWx] = useState<WeatherCost | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [justSent, setJustSent] = useState(false);

  useEffect(() => {
    setD(null); setErr(null); setJustSent(false); setNote("");
    api.overlap(id).then(setD).catch((e) => setErr(String(e.message ?? e)));
    setWx(null);
    api.get<WeatherCost>(`/api/app/hazards/exposure?kind=zone&id=${id}&period=month&month=${THIS_MONTH}&cost=1`).then(setWx).catch(() => setWx(null));  // this month's weather cost
  }, [id]);

  const req = latestFor(requests, id);
  const send = async () => {
    if (!d) return;
    setSending(true); setErr(null);
    try {
      onSent(await requestsApi.send(me, d, note));
      setJustSent(true); setNote(""); say(`Request sent to ${company(partnerOf(me, d)).name}!`, "happy");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e)); say("That request didn't go through.", "sad");
    } finally { setSending(false); }
  };

  if (!d) return <><PanelHeader title={`Overlap #${id}`} onBack={onBack} /><p className="text-sm text-muted">{err ?? <span className="dots">Loading</span>}</p></>;
  const s = sides(me, d);
  const them = company(partnerOf(me, d));
  const ourJob = d.a.id === s.ours.job ? d.a : d.b;
  const theirJob = d.a.id === s.ours.job ? d.b : d.a;
  const budget = (ourJob.cost_usd ?? 0) + (theirJob.cost_usd ?? 0);
  const none = noSavings({ ...d, savings_high: d.savings.high });

  return (
    <>
      <PanelHeader title={`Overlap #${d.id}`} sub={<TierChip tier={d.tier} />} onBack={onBack} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-4 overflow-y-auto pr-2">
        <div className="grid grid-cols-2 gap-2">
          <Stat label="Closest" value={miles(d.distance_m)} hint="Closest distance between the two projects" />
          <Stat label="Drive" value={d.drive_min != null ? `${Math.round(d.drive_min)} min` : "n/a"} hint="Road drive time between the sites" />
          <Stat label="Same time" value={`${Math.round(d.time_overlap * 100)}%`} hint="How much of the shorter build window overlaps the other" />
          <Stat label="Kind" value={TIER_LABEL[d.tier]?.hint ?? d.tier} />
        </div>

        <section className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-faint">Projects</h3>
          <ProjectBlock who={`Ours · ${me.name}`} color={company(me.company).color} name={s.ours.name} start={s.ours.start} end={s.ours.end}
            extra={[ourJob.voltage_kv && `${ourJob.voltage_kv} kV`, ourJob.cost_usd && usd(ourJob.cost_usd)].filter(Boolean).join(" · ")} />
          <ProjectBlock who={`Theirs · ${them.name}`} color={them.color} name={s.theirs.name} start={s.theirs.start} end={s.theirs.end}
            extra={[theirJob.voltage_kv && `${theirJob.voltage_kv} kV`, theirJob.cost_usd && usd(theirJob.cost_usd)].filter(Boolean).join(" · ")} />
        </section>

        {none ? (
          <section className="card-still px-3 py-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-faint">Cost analysis</h3>
            <div className="mt-0.5 font-logo text-xl font-semibold">No savings right now</div>
            <p className="mt-1 text-xs leading-snug text-muted">{none.long}</p>
            {budget > 0 && <p className="mt-1 text-xs leading-snug text-muted">The combined budget is {usd(budget)}, so it is worth a heads up if either schedule moves.</p>}
          </section>
        ) : (
        <section className="rounded-2xl border-2 border-save/30 bg-save-soft/60 px-3 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-faint">Cost analysis</h3>
          <div className="mt-0.5 font-logo text-2xl font-semibold tabular-nums text-save">{usd(d.savings.low)} to {usd(d.savings.high)}</div>
          <div className="text-xs text-muted">Estimated savings from working together{budget > 0 && `, on ${usd(budget)} of combined budget`}.</div>
          <SavingsTable s={d.savings} />
          <p className="mt-2 text-xs text-muted">
            {savingsNote(d.savings)}{" "}
            <a href={METHOD_DOC} target="_blank" rel="noreferrer" className="font-semibold text-grape underline">How this is worked out</a>
          </p>
        </section>
        )}

        {wx?.cost && wx.cost.total.high > 0 && (
          <p className="-mt-2 flex flex-wrap items-center gap-x-1 rounded-2xl border-2 border-warn/25 bg-warn-soft/60 px-3 py-2 text-xs leading-snug">
            <span>Weather in a typical {MONTH_NAME} adds <b className="tabular-nums">{usd(wx.cost.total.low)} to {usd(wx.cost.total.high)}</b>{wx.coordination && wx.coordination.savings.high > 0 && <>; coordinating saves <b className="tabular-nums">{usd(wx.coordination.savings.low)} to {usd(wx.coordination.savings.high)}</b> of that</>}.</span>
            {onHazards && <button onClick={() => onHazards(id, THIS_MONTH)} className="font-semibold text-grape underline">See hazards</button>}
          </p>
        )}
        {d.shareable.length > 0 && (
          <section>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">What you could share</h3>
            <div className="flex flex-wrap gap-1.5">{d.shareable.map((x) => <Chip key={x} tone="info"><span className="capitalize">{x}</span></Chip>)}</div>
          </section>
        )}

        <FeasibilitySection id={d.id} partner={them.name} />

        <NotesBlock kind="overlap" id={String(d.id)} onNotebook={onNotebook} />

        <section className="rounded-2xl border-2 border-pen px-3 py-3">
          <h3 className="mb-1 flex items-center gap-1.5 font-logo text-base font-semibold"><Handshake size={17} /> Collaborate</h3>
          {(justSent && !req) || (req?.status === "pending" && req.from_company === me.company) ? (  // the live status wins once it arrives
            <div className="pop-in">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-save"><Check size={16} /> Collaboration request sent</p>
              <p className="mt-0.5 text-xs text-muted">We'll let you know when {them.name} answers.</p>
            </div>
          ) : req?.status === "pending" ? (
            <div>
              <p className="text-sm">{them.name} sent you a request for this overlap.</p>
              <button onClick={() => onOpenRequest(req.id)} className="pen-btn mt-2 bg-grape px-4 py-1.5 text-sm font-semibold text-white">Review request</button>
            </div>
          ) : (
            <>
              {req && (
                <div className="mb-2 text-sm">
                  <StatusChip status={req.status} /> <span className="text-muted">{req.from_company === me.company ? `by ${them.name}` : "by you"} {ago(req.responded_at ?? req.created_at)}</span>
                  {req.feedback && <p className="mt-1 rounded-xl bg-soft px-2.5 py-1.5 text-xs italic">"{req.feedback}"</p>}
                  <button onClick={() => onOpenRequest(req.id)} className="mt-1 text-xs font-semibold text-grape underline">See request</button>
                </div>
              )}
              {req?.status !== "approved" && (
                <>
                  <p className="mb-1.5 text-sm text-muted">Ask {them.name} to plan this work together.</p>
                  <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} maxLength={2000} placeholder="Add a note (optional)"
                    className="w-full resize-none rounded-xl border-2 border-line px-2.5 py-2 text-sm outline-none focus:border-pen" />
                  <button onClick={send} disabled={sending} className="pen-btn mt-2 flex w-full items-center justify-center gap-2 bg-grape px-4 py-2 text-sm font-semibold text-white">
                    <Send size={15} /> {sending ? "Sending..." : "Send collaboration request"}
                  </button>
                </>
              )}
            </>
          )}
          {err && <p className="mt-2 text-xs text-warn">{err}</p>}
        </section>
      </div>
    </>
  );
}

export function RequestPanel({ me, id, requests, onBack, onOpenOverlap, onResponded }: {
  me: Me; id: number; requests: CollabRequest[]; onBack: () => void; onOpenOverlap: (id: number) => void; onResponded: (r: CollabRequest) => void;
}) {
  const r = requests.find((x) => x.id === id);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState<"approved" | "declined" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!r) return <><PanelHeader title="Request" onBack={onBack} /><p className="text-sm text-muted">Loading...</p></>;
  const incoming = r.to_company === me.company;
  const them = company(incoming ? r.from_company : r.to_company);

  const answer = async (decision: "approved" | "declined") => {
    setBusy(decision); setErr(null);
    try {
      onResponded(await requestsApi.respond(r.id, decision, feedback));
      say(decision === "approved" ? "Approved! I'll let them know." : "Declined. I'll pass on your feedback.", decision === "approved" ? "happy" : "nod");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  return (
    <>
      <PanelHeader title={incoming ? "Collaboration request" : "Your request"} onBack={onBack}
        sub={<span className="flex items-center gap-1.5">{incoming ? <ArrowDownLeft size={14} /> : <ArrowUpRight size={14} />}
          {incoming ? `from ${them.name}` : `to ${them.name}`} · {ago(r.created_at)}</span>} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
        <div className="card-still px-3 py-2.5">
          <div className="mb-1 flex items-center gap-2"><TierChip tier={r.summary.tier} /><span className="text-xs font-semibold tabular-nums text-faint">#{r.opportunity_id}</span><span className="flex-1" /><StatusChip status={r.status} /></div>
          <div className="text-sm font-semibold leading-snug">{incoming ? r.summary.theirs : r.summary.ours}</div>
          <div className="text-xs text-muted">with {incoming ? r.summary.ours : r.summary.theirs}</div>
          {r.summary.savings_high > 0 && <div className="mt-1 text-xs font-semibold tabular-nums text-save">Estimated savings {usd(r.summary.savings_low)} to {usd(r.summary.savings_high)}</div>}
          <button onClick={() => onOpenOverlap(r.opportunity_id)} className="mt-2 inline-flex items-center gap-1 rounded-full border-2 border-pen bg-white px-2.5 py-1 text-xs font-semibold hover:bg-grape-soft"><MapPin size={12} /> Open overlap #{r.opportunity_id}</button>
        </div>

        {r.note && (
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">{incoming ? `Note from ${them.short}` : "Your note"}</div>
            <p className="rounded-2xl rounded-tl-sm bg-soft px-3 py-2 text-sm">{r.note}</p>
          </div>
        )}

        {r.status === "pending" && incoming ? (
          <div className="flex flex-col gap-2">
            <label className="text-xs font-semibold uppercase tracking-wide text-faint" htmlFor="fb">Your feedback</label>
            <textarea id="fb" value={feedback} onChange={(e) => setFeedback(e.target.value)} rows={3} maxLength={2000} placeholder="Optional: share timing, contacts or conditions"
              className="w-full resize-none rounded-xl border-2 border-line px-2.5 py-2 text-sm outline-none focus:border-pen" />
            <div className="flex gap-2">
              <button onClick={() => answer("approved")} disabled={!!busy} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-save px-3 py-2 text-sm font-semibold text-white">
                <Check size={16} /> {busy === "approved" ? "..." : "Approve"}
              </button>
              <button onClick={() => answer("declined")} disabled={!!busy} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-white px-3 py-2 text-sm font-semibold">
                <X size={16} /> {busy === "declined" ? "..." : "Decline"}
              </button>
            </div>
          </div>
        ) : r.status === "pending" ? (
          <p className="flex items-center gap-1.5 text-sm text-muted"><Clock3 size={15} /> Waiting for {them.name} to answer.</p>
        ) : (
          <div className="pop-in">
            <p className="text-sm"><StatusChip status={r.status} /> <span className="text-muted">{incoming ? "by you" : `by ${them.name}`} {ago(r.responded_at ?? r.created_at)}</span></p>
            {r.feedback && (
              <div className="mt-2">
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">{incoming ? "Your feedback" : `Feedback from ${them.short}`}</div>
                <p className="rounded-2xl rounded-tl-sm bg-soft px-3 py-2 text-sm">{r.feedback}</p>
              </div>
            )}
          </div>
        )}
        {err && <p className="text-xs text-warn">{err}</p>}
      </div>
    </>
  );
}

export function HistoryPanel({ me, requests, onBack, onOpen, onGoals, onFindings }: { me: Me; requests: CollabRequest[]; onBack: () => void; onOpen: (id: number) => void; onGoals?: () => void; onFindings?: () => void }) {
  const [tab, setTab] = useState<"all" | "sent" | "received">("all");
  const rows = requests.filter((r) => tab === "all" || (tab === "sent") === (r.from_company === me.company));
  return (
    <>
      <PanelHeader title="Request history" sub={`${requests.length} request${requests.length === 1 ? "" : "s"}`} onBack={onBack}
        right={(onGoals || onFindings) && <span className="mt-1 flex gap-1">
          {onGoals && <button onClick={onGoals} className="rounded-full bg-grape-soft px-2.5 py-1 text-xs font-semibold text-grape hover:bg-grape hover:text-white">Goals</button>}
          {onFindings && <button onClick={onFindings} className="rounded-full bg-grape-soft px-2.5 py-1 text-xs font-semibold text-grape hover:bg-grape hover:text-white">Notebook</button>}
        </span>} />
      <div className="mb-2 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
        {(["all", "sent", "received"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`flex-1 rounded-full py-1 capitalize ${tab === t ? "bg-white shadow-sm" : "text-muted"}`}>{t}</button>
        ))}
      </div>
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto px-0.5 pb-1 pr-2">
        {rows.map((r) => {
          const out = r.from_company === me.company;
          return (
            <ListRow key={r.id} onClick={() => onOpen(r.id)} right={<StatusChip status={r.status} />}
              lead={<span className={`grid h-7 w-7 place-items-center rounded-full ${out ? "bg-grape-soft text-grape" : "bg-crew-soft text-[#8a5a00]"}`}>{out ? <ArrowUpRight size={15} /> : <ArrowDownLeft size={15} />}</span>}
              title={out ? r.summary.ours : r.summary.theirs}
              sub={`${out ? `To ${company(r.to_company).short}` : `From ${company(r.from_company).short}`} · ${ago(r.created_at)}`} />
          );
        })}
        {!rows.length && <p className="px-2 py-6 text-center text-sm text-muted">No requests yet. Open an overlap to send one.</p>}
      </div>
    </>
  );
}
