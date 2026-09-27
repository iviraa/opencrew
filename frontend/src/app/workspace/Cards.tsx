import { AlarmClock, Bookmark, Building2, CalendarCheck, ExternalLink, History, KanbanSquare, MapPin, NotebookPen, StickyNote, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
export type { WorkspaceCard } from "./types";
import { STATUS_LABEL, notesApi, type BriefData, type BriefReq, type HistoryData, type Note, type NotesData, type PipelineData, type ProfileData, type RemindersData, type ViewsData, type WorkspaceCard } from "./types";

type Nav = {
  onOpen?: (overlapId: number) => void; onOpenRequest?: (id: number) => void; onOpenPlan?: (id: number) => void; onNotebook?: () => void;
  onAsk?: (prompt: string) => void; onOpenView?: (name: string) => void;
};

const Card = ({ icon, title, sub, children }: { icon: React.ReactNode; title: string; sub?: string; children?: React.ReactNode }) => (
  <div className="pop-in flex flex-col gap-1.5 rounded-2xl border-2 border-pen bg-white p-2">
    <div className="px-1 pt-0.5">
      <div className="flex items-center gap-2 text-xs font-semibold text-faint">{icon} {title}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
    {children}
  </div>
);

const Link = ({ onClick, children }: { onClick?: () => void; children: React.ReactNode }) => (
  <button onClick={onClick} disabled={!onClick} className="text-xs font-semibold text-grape hover:underline disabled:text-muted disabled:no-underline">{children}</button>
);

// the workspace cards, one per tool result
export default function WorkspaceCardView({ card, ...nav }: { card: WorkspaceCard } & Nav) {
  switch (card.kind) {
    case "note": return <NoteCard data={card.data} {...nav} />;
    case "reminder": return <ReminderCard data={card.data} {...nav} />;
    case "pipeline": return <PipelineCard data={card.data} {...nav} />;
    case "profile": return <ProfileCard data={card.data} {...nav} />;
    case "brief": return <BriefCard data={card.data} {...nav} />;
    case "history": return <HistoryCard data={card.data} {...nav} />;
    case "views": return <ViewsCard data={card.data} {...nav} />;
    case "view": return <Card icon={<Bookmark size={13} />} title={`View: ${card.data.name}`} sub="Brought back on screen" />;
  }
}

function targetLink(n: Note, nav: Nav) {
  if (n.target_kind === "overlap" && nav.onOpen) return <Link onClick={() => nav.onOpen!(Number(n.target_id))}>overlap #{n.target_id}</Link>;
  return <span className="text-xs text-muted">{n.target_kind} {n.target_id}</span>;
}

function NoteCard({ data, ...nav }: { data: NotesData } & Nav) {
  return (
    <Card icon={<StickyNote size={13} />} title={data.target?.label ? `Notes on ${data.target.label}` : "Our notes"} sub={`${data.count} note${data.count === 1 ? "" : "s"}`}>
      {data.notes.slice(0, 8).map((n) => (
        <div key={n.id} className="rounded-xl bg-soft px-2.5 py-1.5 text-sm">
          <div>{n.text}</div>
          <div className="mt-0.5 flex items-center gap-2 text-xs text-faint">{n.when}{!data.target && <>· {targetLink(n, nav)}</>}</div>
        </div>
      ))}
      {!data.notes.length && <p className="px-1 text-xs text-muted">Nothing noted yet.</p>}
    </Card>
  );
}

function ReminderCard({ data, ...nav }: { data: RemindersData } & Nav) {
  return (
    <Card icon={<AlarmClock size={13} />} title={data.saved ? "Reminder set" : data.done ? "Reminder done" : "Reminders"} sub={data.delivery ?? `${data.count} open`}>
      {data.reminders.slice(0, 8).map((r) => (
        <div key={r.id} className={`flex items-start gap-2 rounded-xl px-2.5 py-1.5 text-sm ${r.overdue ? "bg-warn-soft" : "bg-soft"}`}>
          <span className="min-w-0 flex-1">
            <span className="block">{r.text}</span>
            <span className="text-xs text-faint">{r.overdue ? "was due" : "due"} {r.due}{r.target_kind === "overlap" && r.target_id && nav.onOpen && <> · <Link onClick={() => nav.onOpen!(Number(r.target_id))}>#{r.target_id}</Link></>}</span>
          </span>
        </div>
      ))}
      {!data.reminders.length && <p className="px-1 text-xs text-muted">No open reminders.</p>}
    </Card>
  );
}

function PipelineCard({ data, ...nav }: { data: PipelineData } & Nav) {
  const live = data.statuses.filter((s) => data.counts[s]);
  return (
    <Card icon={<KanbanSquare size={13} />} title="Pipeline" sub={live.map((s) => `${STATUS_LABEL[s] ?? s} ${data.counts[s]}`).join(" · ")}>
      <div className="thin-scroll flex gap-1.5 overflow-x-auto pb-1">
        {live.map((s) => (
          <div key={s} className="w-[150px] shrink-0 rounded-xl bg-soft p-1.5">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-faint">{STATUS_LABEL[s] ?? s} · {data.counts[s]}</div>
            {data.columns[s]?.map((it) => (
              <button key={it.id} onClick={() => nav.onOpen?.(it.id)} className="mb-1 block w-full rounded-lg bg-white px-2 py-1 text-left hover:bg-grape-soft">
                <span className="line-clamp-1 text-xs font-semibold">#{it.id} {it.ours}</span>
                <span className="block text-[11px] text-muted">{it.partner} · {it.savings}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      {!live.length && <p className="px-1 text-xs text-muted">No overlaps in the pipeline yet.</p>}
    </Card>
  );
}

function ProfileCard({ data, ...nav }: { data: ProfileData } & Nav) {
  const c = data.company;
  return (
    <Card icon={<Building2 size={13} />} title={c.name} sub={[c.home_state && `home state ${c.home_state}`, c.states.length > 1 && `works in ${c.states.join(", ")}`, c.planner && `plans via ${c.planner}`].filter(Boolean).join(" · ")}>
      <div className="grid grid-cols-2 gap-1.5 text-xs">
        <div className="rounded-xl bg-soft px-2.5 py-1.5"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Projects</div><div className="font-logo text-base font-semibold">{data.projects.total}</div>
          <div className="text-muted">{data.projects.by_kv.slice(0, 3).map((k) => `${k.kv ?? "?"} kV ${k.n}`).join(" · ")}</div></div>
        {!data.is_us && <div className="rounded-xl bg-soft px-2.5 py-1.5"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Overlaps with us</div>
          <div className="font-logo text-base font-semibold">{data.overlaps_with_us.count}</div><div className="text-muted">up to {data.overlaps_with_us.savings_high_total} in savings</div></div>}
        {!data.is_us && <div className="col-span-2 rounded-xl bg-soft px-2.5 py-1.5"><div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Requests with us</div>
          <div className="text-muted">{data.requests_with_us.total} total · {data.requests_with_us.approved} approved · {data.requests_with_us.declined} declined · {data.requests_with_us.pending} pending
            {data.requests_with_us.median_response_hours != null && <> · answers in about {data.requests_with_us.median_response_hours} h</>}</div></div>}
      </div>
      {data.overlaps_with_us.top.map((o) => (
        <button key={o.id} onClick={() => nav.onOpen?.(o.id)} className="rounded-xl border-2 border-line px-2.5 py-1.5 text-left hover:border-pen">
          <span className="line-clamp-1 text-xs font-semibold">#{o.id} {o.ours}</span><span className="block text-[11px] text-muted">with {o.theirs} · {o.savings}</span>
        </button>
      ))}
      {data.news.slice(0, 3).map((n) => (
        <a key={n.url} href={n.url} target="_blank" rel="noreferrer" className="flex items-start gap-1.5 px-1 text-xs hover:underline"><ExternalLink size={12} className="mt-0.5 shrink-0 text-faint" /><span className="line-clamp-2">{n.title} <span className="text-faint">· {n.impact} · {n.date}</span></span></a>
      ))}
      {data.notes.slice(0, 3).map((n) => <div key={n.id} className="rounded-xl bg-soft px-2.5 py-1 text-xs">{n.text}</div>)}
    </Card>
  );
}

function ReqLine({ r, ...nav }: { r: BriefReq } & Nav) {
  return (
    <button onClick={() => nav.onOpenRequest?.(r.id)} className="block w-full rounded-lg px-2 py-1 text-left text-xs hover:bg-soft">
      <span className="font-semibold">#{r.overlap_id}</span> with {r.with} <span className="text-faint">· {r.status} · since {r.since}</span>
    </button>
  );
}

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="rounded-xl bg-soft px-2 py-1.5"><div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-faint">{title}</div>{children}</div>
);

function BriefCard({ data, ...nav }: { data: BriefData } & Nav) {
  return (
    <Card icon={<CalendarCheck size={13} />} title={`Weekly brief · ${data.week_of}`} sub={data.since_last_brief ? `since ${data.since_last_brief}` : "first brief; changes show from next time"}>
      <Section title={`Overlaps · ${data.overlaps.total}`}>
        <div className="text-xs">{data.overlaps.new.length ? <>New: {data.overlaps.new.map((id) => <Link key={id} onClick={() => nav.onOpen?.(id)}>#{id} </Link>)}</> : "No new overlaps."}
          {data.overlaps.gone.length > 0 && <> Gone: {data.overlaps.gone.map((id) => `#${id}`).join(", ")}</>}</div>
      </Section>
      <Section title={`Requests · ${data.requests.waiting_on_us.length} waiting on us · ${data.requests.waiting_on_them.length} on them`}>
        {data.requests.waiting_on_us.map((r) => <ReqLine key={r.id} r={r} {...nav} />)}
        {data.requests.waiting_on_them.map((r) => <ReqLine key={r.id} r={r} {...nav} />)}
        {data.requests.answered_this_week.length > 0 && <div className="px-2 text-xs text-muted">{data.requests.answered_this_week.length} answered this week</div>}
        {!data.requests.waiting_on_us.length && !data.requests.waiting_on_them.length && <div className="px-2 text-xs text-muted">Nothing pending.</div>}
      </Section>
      {data.plan && <Section title="Plan">
        <div className="text-xs">{data.plan.pairs} pairs, {data.plan.proposed} still to decide, {data.plan.accepted} accepted · {data.plan.savings} <Link onClick={() => nav.onOpenPlan?.(data.plan!.id)}>open</Link></div>
      </Section>}
      {data.hazards_this_week.length > 0 && <Section title="Hazards at active sites this week">
        {data.hazards_this_week.map((h) => <div key={h.project} className="line-clamp-1 text-xs">{h.project}: {h.hazards.join(", ")}</div>)}
      </Section>}
      {data.news.length > 0 && <Section title="News about us">
        {data.news.map((n) => <a key={n.url} href={n.url} target="_blank" rel="noreferrer" className="line-clamp-1 block text-xs hover:underline">{n.title} <span className="text-faint">· {n.impact}</span></a>)}
      </Section>}
      {data.findings_starred.length > 0 && <Section title="Findings starred this week">
        {data.findings_starred.map((f) => <div key={f.id} className="line-clamp-1 text-xs">{f.title}</div>)}
        <Link onClick={nav.onNotebook}>open notebook</Link>
      </Section>}
    </Card>
  );
}

const KIND_COLOR: Record<string, string> = { status: "#5b2bb5", request: "#ffb020", request_sent: "#ffb020", request_received: "#ffb020", approved: "#12a36b", declined: "#c23b3b", assessment: "#00b8a9", finding: "#7c4dff", note: "#8a94b0" };

function HistoryCard({ data, ...nav }: { data: HistoryData } & Nav) {
  return (
    <Card icon={<History size={13} />} title={`History of #${data.opportunity_id}`} sub={`${data.ours} with ${data.partner} · now ${STATUS_LABEL[data.status] ?? data.status}`}>
      <div className="flex flex-col">
        {data.events.map((e, i) => (
          <div key={i} className="flex gap-2 px-1 py-0.5 text-xs">
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[e.kind] ?? "#8a94b0" }} />
            <span className="min-w-0"><span className="text-faint">{e.when}</span> · {e.text}</span>
          </div>
        ))}
        {!data.events.length && <p className="px-1 text-xs text-muted">Nothing has happened on this overlap yet.</p>}
      </div>
      <div className="flex gap-2 px-1"><Link onClick={() => nav.onOpen?.(data.opportunity_id)}>open overlap</Link></div>
    </Card>
  );
}

function ViewsCard({ data, ...nav }: { data: ViewsData } & Nav) {
  return (
    <Card icon={<Bookmark size={13} />} title="Saved views" sub={`${data.length} saved`}>
      {data.map((v) => (
        <button key={v.id} onClick={() => nav.onOpenView?.(v.name)} className="flex items-center gap-2 rounded-xl bg-soft px-2.5 py-1.5 text-left text-sm hover:bg-grape-soft">
          <MapPin size={13} className="shrink-0 text-faint" /><span className="flex-1 font-semibold">{v.name}</span><span className="text-xs text-faint">{v.when}</span>
        </button>
      ))}
      {!data.length && <p className="px-1 text-xs text-muted">No saved views. Say "save this view as ...".</p>}
    </Card>
  );
}

// notes on one target, inside a detail panel; written with the person's own login
export function NotesBlock({ kind, id }: { kind: string; id: string }) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => notesApi.list(kind, id).then(setNotes).catch(() => setNotes([]));
  useEffect(() => { refresh(); }, [kind, id]);  // eslint-disable-line react-hooks/exhaustive-deps
  const add = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await notesApi.add(kind, id, text); setText(""); await refresh(); } finally { setBusy(false); }
  };
  return (
    <section>
      <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-muted"><NotebookPen size={14} /> Notes{notes.length ? ` · ${notes.length}` : ""}</h3>
      {notes.slice(0, 5).map((n) => (
        <div key={n.id} className="mb-1 flex items-start gap-1.5 rounded-xl bg-soft px-2.5 py-1.5 text-xs">
          <span className="min-w-0 flex-1"><span className="block">{n.text}</span><span className="text-faint">{n.when}</span></span>
          <button onClick={() => notesApi.remove(n.id).then(refresh)} aria-label="Delete note" className="text-faint hover:text-warn"><Trash2 size={12} /></button>
        </div>
      ))}
      <form onSubmit={(e) => { e.preventDefault(); add(); }} className="flex items-center gap-1 rounded-full border-2 border-line bg-white py-0.5 pl-3 pr-0.5 focus-within:border-pen">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Add a note for the team" className="min-w-0 flex-1 bg-transparent text-xs outline-none" />
        <button disabled={busy || !text.trim()} className="rounded-full bg-grape px-2.5 py-1 text-xs font-semibold text-white disabled:opacity-40">Add</button>
      </form>
    </section>
  );
}
