import DOMPurify from "dompurify";
import { marked } from "marked";
import { ArrowUp, Brain, CloudOff, Eraser, NotebookPen, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Confirm from "./Confirm";
import { company, type ChatAction, type CollabRequest, type Me, type Overlap } from "./data";
import { GoalChip } from "./GoalPanel";
import MemoryList from "./Memory";
import { OverlapCard, latestFor } from "./panels";
import ChartCard from "./generate/ChartCard";
import ReportCard from "./generate/ReportCard";
import TableCard from "./generate/TableCard";
import type { Chart, Report, Table } from "./generate/types";
import PlanCard from "./plan/PlanCard";
import CompareCard from "./findings/CompareCard";
import FindingCard from "./findings/FindingCard";
import type { PickPlace } from "./findings/Knobs";
import type { Comparison, Finding } from "./findings/types";
import type { PlanStore } from "./plan/usePlans";
import DraftCard from "./comms/DraftCard";
import type { Draft } from "./comms/types";
import WorkspaceCardView, { type WorkspaceCard } from "./workspace/Cards";

export type ChatMsg = {
  role: "user" | "model"; text: string; ids?: number[]; title?: string; offline?: boolean; confirm?: ChatAction[]; goal?: number;
  plan?: { id: number; horizon?: string; item?: string }; chart?: Chart; table?: Table; report?: Report; finding?: Finding; compare?: Comparison; draft?: Draft;
  workspace?: WorkspaceCard;
};

const html = (s: string) => DOMPurify.sanitize(marked.parse(s, { async: false }) as string);

export default function Chat({ me, msgs, busy, overlaps, requests, plans, onSend, onOpen, onClose, onDone, onOpenRequest, onOpenGoal, onOpenPlan, onClear, memoryTick = 0,
  partners = [], onOverlay, onPickPlace, picking, onCompare, onNotebook, onOpenView }: {
  me: Me; msgs: ChatMsg[]; busy: boolean; overlaps: Overlap[] | null; requests: CollabRequest[]; plans: PlanStore;
  onSend: (text: string) => void; onOpen: (id: number) => void; onClose: () => void;
  onDone: (r: CollabRequest) => void; onOpenRequest: (id: number) => void; onOpenGoal: (id: number) => void; onOpenPlan: (id: number, item?: string) => void;
  onClear?: () => void; memoryTick?: number;
  partners?: string[]; onOverlay?: (f: Finding | null) => void; onPickPlace?: PickPlace; picking?: boolean; onCompare?: (f: Finding) => void; onNotebook?: () => void; onOpenView?: (name: string) => void;
}) {
  const [text, setText] = useState("");
  const [showMemory, setShowMemory] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const byId = new Map((overlaps ?? []).map((o) => [o.id, o]));
  const lastSent = requests.find((r) => r.from_company === me.company);  // newest first
  const ideas = [
    lastSent ? `Did ${company(lastSent.to_company).name} approve my last request?` : "Any requests waiting for me?",
    "Plan my next quarter",
    "What if we shift #18 by 3 months?",
    "Chart our weather-affected days by month for our best overlap",
    "What overlaps happen in 2025?",
    "Show crossings and same-land overlaps",
    "Any severe weather coming this week?",
  ];

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs.length, busy]);

  const send = (t: string) => {
    if (!t.trim() || busy) return;
    onSend(t.trim()); setText("");
  };

  return (
    <>
      <div className="flex items-center gap-2 pb-3">
        <div className="min-w-0 flex-1">
          <h2 className="font-logo text-xl font-semibold leading-tight">Ask Crewly</h2>
          <div className="text-sm text-muted">Overlaps, plans, requests, weather</div>
        </div>
        {onNotebook && <button onClick={onNotebook} aria-label="Saved findings" title="Saved findings" className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-grape-soft"><NotebookPen size={16} /></button>}
        <button onClick={() => setShowMemory(!showMemory)} aria-label="What Crewly remembers" aria-pressed={showMemory} title="What Crewly remembers"
          className={`grid h-8 w-8 place-items-center rounded-full hover:bg-grape-soft ${showMemory ? "bg-grape-soft text-grape" : "text-muted"}`}><Brain size={16} /></button>
        {onClear && msgs.length > 0 && (
          <button onClick={onClear} aria-label="Clear chat" title="Clear chat" className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-grape-soft"><Eraser size={16} /></button>
        )}
        <button onClick={onClose} aria-label="Close chat" className="grid h-8 w-8 place-items-center rounded-full border-2 border-pen bg-white hover:bg-grape-soft"><X size={16} strokeWidth={2.5} /></button>
      </div>

      {showMemory && <MemoryList tick={memoryTick} />}

      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2.5 overflow-y-auto pr-2">
        {!msgs.length && (
          <div className="pop-in flex flex-col gap-2">
            <p className="rounded-2xl rounded-tl-sm bg-soft px-3 py-2 text-sm">Hi! I'm Crewly. Ask me about overlaps, dates, your requests or the weather. I'll put answers on the map too.</p>
            {ideas.map((q) => (
              <button key={q} onClick={() => send(q)} className="self-start rounded-full border-2 border-line px-3 py-1 text-left text-xs font-semibold hover:border-pen">{q}</button>
            ))}
          </div>
        )}
        {msgs.map((m, i) => m.role === "user" ? (
          <p key={i} className="pop-in max-w-[88%] self-end rounded-2xl rounded-tr-sm bg-grape px-3 py-2 text-sm text-white">{m.text}</p>
        ) : (
          <div key={i} className="pop-in flex flex-col gap-1.5">
            {m.offline ? (
              <p className="flex max-w-[95%] gap-2 rounded-2xl rounded-tl-sm bg-warn-soft px-3 py-2 text-sm text-ink"><CloudOff size={16} className="mt-0.5 shrink-0 text-warn" />{m.text}</p>
            ) : (
              <div className="crewly max-w-[95%] rounded-2xl rounded-tl-sm bg-soft px-3 py-2 text-sm" dangerouslySetInnerHTML={{ __html: html(m.text) }} />
            )}
            {m.confirm?.map((a, j) => (
              <Confirm key={j} me={me} action={a} overlaps={overlaps} requests={requests} onDone={onDone} onOpenRequest={onOpenRequest} />
            ))}
            {m.goal != null && <GoalChip id={m.goal} onOpen={() => onOpenGoal(m.goal!)} />}
            {m.plan && <PlanCard store={plans} id={m.plan.id} horizon={m.plan.horizon} item={m.plan.item} onOpenPlan={onOpenPlan} onOpenGoal={onOpenGoal} />}
            {m.chart && <ChartCard chart={m.chart} />}
            {m.table && <TableCard table={m.table} />}
            {m.report && <ReportCard report={m.report} />}
            {m.finding && <FindingCard finding={m.finding} partners={partners} onOpen={onOpen} onOverlay={onOverlay} onPickPlace={onPickPlace} picking={picking} onCompare={onCompare} />}
            {m.compare && <CompareCard comparison={m.compare} />}
            {m.draft && <DraftCard draft={m.draft} />}
            {m.workspace && <WorkspaceCardView card={m.workspace} onOpen={onOpen} onOpenRequest={onOpenRequest} onOpenPlan={(id) => onOpenPlan(id)} onNotebook={onNotebook} onAsk={send} onOpenView={onOpenView} />}
            {m.ids && m.ids.length > 0 && m.goal == null && !m.plan && (
              <div className="flex flex-col gap-1 rounded-2xl border-2 border-line p-1">
                <div className="px-2 pt-1 text-xs font-semibold text-faint">{m.title ?? `${m.ids.length} on the map`} · tap one for details</div>
                {m.ids.map((id) => byId.get(id)).filter((o): o is Overlap => !!o).map((o) => (
                  <OverlapCard key={o.id} me={me} o={o} req={latestFor(requests, o.id)} onClick={() => onOpen(o.id)} />
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="typing flex gap-1 self-start rounded-2xl rounded-tl-sm bg-soft px-3 py-3"><span /><span /><span /></div>}
        <div ref={end} />
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="mt-2 flex items-center gap-2 rounded-full border-2 border-pen bg-white py-1 pl-4 pr-1">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask anything..." className="min-w-0 flex-1 bg-transparent text-sm outline-none" autoFocus />
        <button disabled={busy || !text.trim()} aria-label="Send" className="grid h-8 w-8 place-items-center rounded-full bg-grape text-white disabled:opacity-40"><ArrowUp size={17} strokeWidth={2.5} /></button>
      </form>
    </>
  );
}
