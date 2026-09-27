import { AlarmClock, Bookmark, Building2, CalendarCheck, ExternalLink, History, KanbanSquare, MapPin, NotebookPen, StickyNote, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
export type { WorkspaceCard } from "./types";
import { Card as Shell, Chip, Drawer, Lead, Note as Hint, Pill, RefLink, Row, StatRow, plural, type ChipTone } from "../ui";
import { STATUS_LABEL, notesApi, type BriefData, type BriefReq, type HistoryData, type Note, type NotesData, type PipelineData, type ProfileData, type RemindersData, type ViewsData, type WorkspaceCard } from "./types";

type Nav = {
  onOpen?: (overlapId: number) => void; onOpenRequest?: (id: number) => void; onOpenPlan?: (id: number) => void; onNotebook?: () => void;
  onAsk?: (prompt: string) => void; onOpenView?: (name: string) => void;
};

const Card = ({ icon, title, sub, children }: { icon: React.ReactNode; title: React.ReactNode; sub?: React.ReactNode; children?: React.ReactNode }) => (
  <Shell icon={icon} title={title} sub={sub}>{children}</Shell>
);
const SHOWN = 4;  // rows in view before the rest fold into a drawer
const STATUS_TONE: Record<string, ChipTone> = { agreed: "good", approved: "good", declined: "warn", pending: "amber", sent: "info", replied: "info", call_scheduled: "info", drafted: "neutral", not_contacted: "neutral" };
const status = (s: string) => <Chip tone={STATUS_TONE[s] ?? "neutral"}>{STATUS_LABEL[s] ?? s.replace(/_/g, " ")}</Chip>;

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
    case "view": return <Card icon={<Bookmark size={15} />} title={`View: ${card.data.name}`} sub="Brought back on screen" />;
  }
}

function targetLink(n: Note, nav: Nav) {
  if (n.target_kind === "overlap") return <RefLink id={Number(n.target_id)} onOpen={nav.onOpen} />;
  return <span className="text-xs text-muted">{n.target_kind} {n.target_id}</span>;
}

// the first few rows in view, the rest behind a drawer so the card stays short
function Fold<T>({ rows, render, more }: { rows: T[]; render: (r: T) => React.ReactNode; more: string }) {
  const head = rows.slice(0, rows.length > SHOWN + 1 ? SHOWN : rows.length), rest = rows.slice(head.length);
  return (<>
    {head.map(render)}
    {rest.length > 0 && <Drawer title={`${rest.length} more ${more}`}>{rest.map(render)}</Drawer>}
  </>);
}

function NoteCard({ data, ...nav }: { data: NotesData } & Nav) {
  return (
    <Card icon={<StickyNote size={15} />} title={data.target?.label ? `Notes on ${data.target.label}` : "Our notes"} sub={plural(data.count, "note")}>
      <Fold rows={data.notes} more="notes" render={(n) => (
        <div key={n.id} className="rounded-xl bg-soft px-2.5 py-1.5 text-sm leading-snug">
          <div>{n.text}</div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-faint">{n.when}{!data.target && <>· {targetLink(n, nav)}</>}</div>
        </div>
      )} />
      {!data.notes.length && <Hint>Nothing noted yet.</Hint>}
    </Card>
  );
}

function ReminderCard({ data, ...nav }: { data: RemindersData } & Nav) {
  const overdue = data.reminders.filter((r) => r.overdue).length;
  return (
    <Card icon={<AlarmClock size={15} />} title={data.saved ? "Reminder set" : data.done ? "Reminder done" : "Reminders"}
      sub={<Row>{overdue > 0 && <Chip tone="warn">{overdue} overdue</Chip>}<span>{data.delivery ?? `${data.count} open`}</span></Row>}>
      <Fold rows={data.reminders} more="reminders" render={(r) => (
        <div key={r.id} className={`flex items-start gap-2 rounded-xl px-2.5 py-1.5 text-sm leading-snug ${r.overdue ? "bg-warn-soft" : "bg-soft"}`}>
          <span className="min-w-0 flex-1">
            <span className="block">{r.text}</span>
            <span className="text-[11px] text-faint">{r.overdue ? "Was due" : "Due"} {r.due}{r.target_kind === "overlap" && r.target_id && <> · <RefLink id={Number(r.target_id)} onOpen={nav.onOpen} /></>}</span>
          </span>
        </div>
      )} />
      {!data.reminders.length && <Hint>No open reminders.</Hint>}
    </Card>
  );
}

function PipelineCard({ data, ...nav }: { data: PipelineData } & Nav) {
  const live = data.statuses.filter((s) => data.counts[s]);
  return (
    <Card icon={<KanbanSquare size={15} />} title="Pipeline" sub={<Row>{live.map((s) => <Chip key={s} tone={STATUS_TONE[s] ?? "neutral"}>{data.counts[s]} {(STATUS_LABEL[s] ?? s).toLowerCase()}</Chip>)}</Row>}>
      <div className="thin-scroll flex gap-1.5 overflow-x-auto pb-1">
        {live.map((s) => (
          <div key={s} className="w-[160px] shrink-0 rounded-xl bg-soft p-1.5">
            <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-faint">{STATUS_LABEL[s] ?? s} · {data.counts[s]}</div>
            {data.columns[s]?.map((it) => (
              <button key={it.id} onClick={() => nav.onOpen?.(it.id)} className="mb-1 block w-full rounded-lg bg-white px-2 py-1 text-left hover:bg-grape-soft">
                <span className="line-clamp-1 text-xs font-semibold">#{it.id} {it.ours}</span>
                <span className="block text-[11px] text-muted">{it.partner} · {it.savings}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      {!live.length && <Hint>No overlaps in the pipeline yet.</Hint>}
    </Card>
  );
}

function ProfileCard({ data, ...nav }: { data: ProfileData } & Nav) {
  const c = data.company, r = data.requests_with_us;
  const kv = data.projects.by_kv.slice(0, 3).map((k) => `${k.kv ?? "?"} kV ${k.n}`).join(" · ");
  return (
    <Card icon={<Building2 size={15} />} title={c.name} sub={[c.home_state && `Home state ${c.home_state}`, c.states.length > 1 && `works in ${c.states.join(", ")}`, c.planner && `plans via ${c.planner}`].filter(Boolean).join(" · ")}>
      <StatRow items={[
        { label: "Projects", value: data.projects.total, note: kv },
        ...(data.is_us ? [] : [{ label: "Overlaps with us", value: data.overlaps_with_us.count, note: `up to ${data.overlaps_with_us.savings_high_total}`, tone: "good" as const }]),
      ]} cols={data.is_us ? 2 : 2} />
      {!data.is_us && r.total > 0 && (
        <Row>
          <Chip>{plural(r.total, "request")} with us</Chip>
          {r.approved > 0 && <Chip tone="good">{r.approved} approved</Chip>}{r.declined > 0 && <Chip tone="warn">{r.declined} declined</Chip>}{r.pending > 0 && <Chip tone="amber">{r.pending} pending</Chip>}
          {r.median_response_hours != null && <Chip tone="info">answers in about {r.median_response_hours} h</Chip>}
        </Row>
      )}
      {data.overlaps_with_us.top.map((o) => (
        <button key={o.id} onClick={() => nav.onOpen?.(o.id)} className="rounded-xl border-2 border-line px-2.5 py-1.5 text-left hover:border-pen">
          <span className="line-clamp-1 text-xs font-semibold">#{o.id} {o.ours}</span><span className="block text-[11px] text-muted">with {o.theirs} · {o.savings}</span>
        </button>
      ))}
      {(data.news.length > 0 || data.notes.length > 0) && (
        <Drawer title="News and notes" summary={[data.news.length && plural(data.news.length, "story", "stories"), data.notes.length && plural(data.notes.length, "note")].filter(Boolean).join(" · ")}>
          {data.news.slice(0, 3).map((n) => (
            <a key={n.url} href={n.url} target="_blank" rel="noreferrer" className="flex items-start gap-1.5 text-xs hover:underline"><ExternalLink size={12} className="mt-0.5 shrink-0 text-faint" /><span className="line-clamp-2">{n.title} <span className="text-faint">· {n.impact} · {n.date}</span></span></a>
          ))}
          {data.notes.slice(0, 3).map((n) => <div key={n.id} className="rounded-xl bg-soft px-2.5 py-1 text-xs">{n.text}</div>)}
        </Drawer>
      )}
    </Card>
  );
}

function ReqLine({ r, ...nav }: { r: BriefReq } & Nav) {
  return (
    <button onClick={() => nav.onOpenRequest?.(r.id)} className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1 text-left text-xs hover:bg-soft">
      <span className="min-w-0 flex-1 truncate"><span className="font-semibold">#{r.overlap_id}</span> with {r.with} <span className="text-faint">· since {r.since}</span></span>{status(r.status)}
    </button>
  );
}

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="rounded-xl bg-soft px-2 py-1.5"><div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-faint">{title}</div>{children}</div>
);

function BriefCard({ data, ...nav }: { data: BriefData } & Nav) {
  const waitUs = data.requests.waiting_on_us.length, waitThem = data.requests.waiting_on_them.length;
  const extras = [data.hazards_this_week.length > 0, data.news.length > 0, data.findings_starred.length > 0].filter(Boolean).length;
  return (
    <Card icon={<CalendarCheck size={15} />} title={`Weekly brief · ${data.week_of}`} sub={data.since_last_brief ? `Changes since ${data.since_last_brief}` : "First brief; changes show from next week"}>
      <Lead>
        {plural(data.overlaps.total, "overlap")} on the board{data.overlaps.new.length ? `, ${data.overlaps.new.length} new` : ""}{data.overlaps.gone.length ? `, ${data.overlaps.gone.length} gone` : ""}.
        {" "}{waitUs ? `${plural(waitUs, "request")} waiting on us` : "Nothing waiting on us"}{waitThem ? `, ${waitThem} on them` : ""}.
        {data.plan ? ` The plan holds ${plural(data.plan.pairs, "pair")} worth ${data.plan.savings}, ${data.plan.proposed} still to decide.` : ""}
      </Lead>
      <StatRow items={[
        { label: "Overlaps", value: data.overlaps.total, note: data.overlaps.new.length ? `${data.overlaps.new.length} new` : "no change" },
        { label: "Waiting on us", value: waitUs, tone: waitUs ? "info" : "flat" },
        { label: "Waiting on them", value: waitThem },
      ]} />
      {data.overlaps.new.length > 0 && <Row><span className="text-[11px] text-muted">New:</span>{data.overlaps.new.map((id) => <RefLink key={id} id={id} onOpen={nav.onOpen} />)}</Row>}
      {(waitUs > 0 || waitThem > 0) && (
        <Drawer title="Requests" summary={`${waitUs} on us · ${waitThem} on them${data.requests.answered_this_week.length ? ` · ${data.requests.answered_this_week.length} answered this week` : ""}`} defaultOpen={waitUs > 0}>
          {data.requests.waiting_on_us.map((r) => <ReqLine key={r.id} r={r} {...nav} />)}
          {data.requests.waiting_on_them.map((r) => <ReqLine key={r.id} r={r} {...nav} />)}
        </Drawer>
      )}
      {data.plan && <Row><Pill onClick={() => nav.onOpenPlan?.(data.plan!.id)}>Open the plan · {data.plan.accepted} accepted</Pill></Row>}
      {extras > 0 && (
        <Drawer title="This week" summary={[data.hazards_this_week.length && `${data.hazards_this_week.length} sites with hazards`, data.news.length && plural(data.news.length, "story", "stories"), data.findings_starred.length && `${data.findings_starred.length} starred`].filter(Boolean).join(" · ")}>
          {data.hazards_this_week.length > 0 && <Section title="Hazards at active sites">
            {data.hazards_this_week.map((h) => <div key={h.project} className="line-clamp-1 text-xs">{h.project}: {h.hazards.join(", ")}</div>)}
          </Section>}
          {data.news.length > 0 && <Section title="News about us">
            {data.news.map((n) => <a key={n.url} href={n.url} target="_blank" rel="noreferrer" className="line-clamp-1 block text-xs hover:underline">{n.title} <span className="text-faint">· {n.impact}</span></a>)}
          </Section>}
          {data.findings_starred.length > 0 && <Section title="Findings starred">
            {data.findings_starred.map((f) => <div key={f.id} className="line-clamp-1 text-xs">{f.title}</div>)}
            <Link onClick={nav.onNotebook}>Open the notebook</Link>
          </Section>}
        </Drawer>
      )}
    </Card>
  );
}

const KIND_COLOR: Record<string, string> = { status: "#5b2bb5", request: "#ffb020", request_sent: "#ffb020", request_received: "#ffb020", approved: "#12a36b", declined: "#c23b3b", assessment: "#00b8a9", finding: "#7c4dff", note: "#8a94b0" };

function HistoryCard({ data, ...nav }: { data: HistoryData } & Nav) {
  return (
    <Card icon={<History size={15} />} title={<>History of <RefLink id={data.opportunity_id} onOpen={nav.onOpen} /></>} sub={<Row><span>{data.ours} with {data.partner}</span>{status(data.status)}</Row>}>
      <div className="flex flex-col">
        <Fold rows={data.events} more="events" render={(e) => (
          <div key={`${e.when}-${e.text}`} className="flex gap-2 px-1 py-0.5 text-xs leading-snug">
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[e.kind] ?? "#8a94b0" }} />
            <span className="min-w-0"><span className="text-faint">{e.when}</span> · {e.text}</span>
          </div>
        )} />
        {!data.events.length && <Hint>Nothing has happened on this overlap yet.</Hint>}
      </div>
    </Card>
  );
}

function ViewsCard({ data, ...nav }: { data: ViewsData } & Nav) {
  return (
    <Card icon={<Bookmark size={15} />} title="Saved views" sub={`${data.length} saved · tap one to bring it back`}>
      <Fold rows={data} more="views" render={(v) => (
        <button key={v.id} onClick={() => nav.onOpenView?.(v.name)} className="flex items-center gap-2 rounded-xl bg-soft px-2.5 py-1.5 text-left text-sm hover:bg-grape-soft">
          <MapPin size={13} className="shrink-0 text-faint" /><span className="flex-1 font-semibold">{v.name}</span><span className="text-[11px] text-faint">{v.when}</span>
        </button>
      )} />
      {!data.length && <Hint>No saved views. Say "save this view as ...".</Hint>}
    </Card>
  );
}

// notes on one target, inside a detail panel; written with the person's own login
export function NotesBlock({ kind, id, onNotebook }: { kind: string; id: string; onNotebook?: () => void }) {
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
      <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-muted"><NotebookPen size={14} /> Notes{notes.length ? ` · ${notes.length}` : ""}
        <span className="flex-1" />{onNotebook && <button type="button" onClick={onNotebook} className="text-xs font-semibold text-grape hover:underline">Open notebook</button>}</h3>
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
