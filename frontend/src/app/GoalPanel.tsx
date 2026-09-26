import { Flag, MapPin, Send, SkipForward } from "lucide-react";
import { useEffect, useState } from "react";
import {
  ago, goals, overlapFor, requests as requestsApi, supabase,
  type AgentTask, type CollabRequest, type GoalStep, type Me, type Overlap,
} from "./data";
import { say } from "./mascot";
import { PanelHeader, StatusChip, VerdictChip } from "./panels";

type State = "draft" | "skipped" | CollabRequest["status"];

export function stepState(s: GoalStep, reqs: CollabRequest[]): State {
  if (s.skipped) return "skipped";
  const r = s.request_id != null ? reqs.find((x) => x.id === s.request_id) : null;
  return r ? r.status : s.request_id != null ? "pending" : "draft";
}

function useGoal(id: number) {
  const [task, setTask] = useState<AgentTask | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    goals.get(id).then(setTask).catch((e) => setErr(String(e.message ?? e)));
    const ch = supabase.channel(`goal-${id}`)
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "agent_task", filter: `id=eq.${id}` }, (p) => setTask(p.new as AgentTask))
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [id]);
  return { task, setTask, err };
}

function StateChip({ state }: { state: State }) {
  if (state === "draft") return <span className="rounded-full bg-grape-soft px-2 py-0.5 text-xs font-semibold text-grape">Draft</span>;
  if (state === "skipped") return <span className="rounded-full bg-soft px-2 py-0.5 text-xs font-semibold text-muted">Skipped</span>;
  return <StatusChip status={state} />;
}

export function GoalChip({ id, onOpen }: { id: number; onOpen: () => void }) {
  const [task, setTask] = useState<AgentTask | null>(null);
  useEffect(() => { goals.get(id).then(setTask).catch(() => {}); }, [id]);
  return (
    <button onClick={onOpen} className="pop-in flex items-center gap-2.5 rounded-2xl border-2 border-pen bg-white px-3 py-2 text-left hover:bg-grape-soft">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-grape text-white"><Flag size={15} /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">Goal: {task ? `${task.steps.length} overlap${task.steps.length === 1 ? "" : "s"} drafted` : "drafted"}</span>
        <span className="block text-xs text-muted">Review and send from the goal panel</span>
      </span>
      <span className="text-sm font-semibold text-grape">Open</span>
    </button>
  );
}

export function GoalPanel({ me, id, overlaps, requests, onBack, onOpenOverlap, onSent }: {
  me: Me; id: number; overlaps: Overlap[] | null; requests: CollabRequest[];
  onBack: () => void; onOpenOverlap: (id: number) => void; onSent: (r: CollabRequest) => void;
}) {
  const { task, setTask, err } = useGoal(id);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [asking, setAsking] = useState<number | "all" | "cancel" | null>(null);  // which button is waiting for its confirm
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {  // every step answered or skipped: the goal is done
    if (!task || task.status !== "active") return;
    const done = task.steps.every((s) => ["approved", "declined", "skipped"].includes(stepState(s, requests)));
    if (done) goals.save(task.id, { status: "done" }).then(setTask).catch(() => {});
  }, [task, requests, setTask]);

  if (!task) return <><PanelHeader title="Goal" onBack={onBack} /><p className="text-sm text-muted">{err ?? <span className="dots">Loading</span>}</p></>;
  const states = task.steps.map((s) => stepState(s, requests));
  const drafts = states.map((s, i) => (s === "draft" ? i : -1)).filter((i) => i >= 0);
  const answered = states.filter((s) => s === "approved" || s === "declined").length;
  const sent = states.filter((s) => s !== "draft" && s !== "skipped").length;
  const skipped = states.filter((s) => s === "skipped").length;
  const live = task.status === "active";

  const save = async (steps: GoalStep[], status?: AgentTask["status"]) => setTask(await goals.save(task.id, status ? { steps, status } : { steps }));
  const noteOf = (i: number) => notes[i] ?? task.steps[i].note;

  const sendSteps = async (idx: number[]) => {
    setBusy(true); setMsg(null);
    const steps = task.steps.map((s) => ({ ...s }));
    let ok = 0;
    for (const i of idx) {
      try {
        const r = await requestsApi.send(me, await overlapFor(steps[i].opportunity_id, overlaps), noteOf(i));
        steps[i] = { ...steps[i], note: noteOf(i), request_id: r.id };
        onSent(r); ok++;
      } catch (e) { setMsg(`#${steps[i].opportunity_id}: ${e instanceof Error ? e.message : e}`); }
    }
    try { await save(steps); } catch (e) { setMsg(String(e instanceof Error ? e.message : e)); }
    if (ok) say(`Sent ${ok} request${ok === 1 ? "" : "s"}!`, "happy");
    setBusy(false); setAsking(null);
  };

  const skip = (i: number) => save(task.steps.map((s, j) => (j === i ? { ...s, skipped: true } : s)));
  const cancel = async () => { await save(task.steps, "cancelled"); setAsking(null); say("Goal cancelled. No problem.", "nod"); };

  return (
    <>
      <PanelHeader title="Goal" sub={task.goal} onBack={onBack} />
      <div className="mb-3">
        <div className="flex justify-between text-xs font-semibold text-muted">
          <span>{sent} of {task.steps.length} sent · {answered} answered{skipped ? ` · ${skipped} skipped` : ""}</span>
          <span>{live ? `started ${ago(task.created_at)}` : task.status}</span>
        </div>
        <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-soft">
          <div className="bg-save transition-all" style={{ width: `${(answered / task.steps.length) * 100}%` }} />
          <div className="bg-crew transition-all" style={{ width: `${((sent - answered) / task.steps.length) * 100}%` }} />
        </div>
      </div>

      {live && (
        <div className="mb-3 flex flex-col gap-1.5">
          {msg && <p className="text-xs text-warn">{msg}</p>}
          {asking === "all" ? (
            <div className="flex gap-2">
              <button onClick={() => sendSteps(drafts)} disabled={busy} className="pen-btn flex-1 bg-grape px-3 py-1.5 text-sm font-semibold text-white">{busy ? "Sending..." : `Confirm: send ${drafts.length}`}</button>
              <button onClick={() => setAsking(null)} className="px-3 text-sm font-semibold text-muted">Cancel</button>
            </div>
          ) : asking === "cancel" ? (
            <div className="flex gap-2">
              <button onClick={cancel} className="pen-btn flex-1 bg-white px-3 py-1.5 text-sm font-semibold">Confirm: cancel goal</button>
              <button onClick={() => setAsking(null)} className="px-3 text-sm font-semibold text-muted">Keep it</button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              {drafts.length > 0 && (
                <button onClick={() => setAsking("all")} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-grape px-3 py-1.5 text-sm font-semibold text-white">
                  <Send size={14} /> Send all drafts ({drafts.length})
                </button>
              )}
              <button onClick={() => setAsking("cancel")} className="px-2 text-xs font-semibold text-muted hover:text-ink">Cancel goal</button>
            </div>
          )}
        </div>
      )}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2 pb-16">
        {task.steps.map((s, i) => {
          const st = states[i];
          return (
            <div key={s.opportunity_id} className={`rounded-2xl border-2 px-3 py-2.5 ${st === "draft" && live ? "border-line" : "border-transparent bg-soft"}`}>
              <div className="mb-1 flex items-center gap-2">
                <StateChip state={st} />{s.feasibility && <VerdictChip verdict={s.feasibility.verdict} score={s.feasibility.score} />}
                <span className="text-xs text-faint">#{s.opportunity_id}</span>
              </div>
              <div className="line-clamp-2 text-sm font-semibold leading-snug">{s.title}</div>
              {st === "draft" && live ? (
                <>
                  <textarea value={noteOf(i)} onChange={(e) => setNotes({ ...notes, [i]: e.target.value })} rows={3} maxLength={2000}
                    className="mt-1.5 w-full resize-none rounded-xl border-2 border-line px-2.5 py-1.5 text-xs outline-none focus:border-pen" />
                  <div className="mt-1 flex items-center gap-1.5">
                    {asking === i ? (
                      <>
                        <button onClick={() => sendSteps([i])} disabled={busy} className="pen-btn flex items-center gap-1 bg-grape px-3 py-1 text-xs font-semibold text-white">
                          <Send size={12} /> {busy ? "..." : "Confirm send"}
                        </button>
                        <button onClick={() => setAsking(null)} className="px-2 py-1 text-xs font-semibold text-muted">Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => setAsking(i)} className="flex items-center gap-1 rounded-full bg-grape px-3 py-1 text-xs font-semibold text-white"><Send size={12} /> Send</button>
                        <button onClick={() => skip(i)} className="flex items-center gap-1 rounded-full px-2 py-1 text-xs font-semibold text-muted hover:text-ink"><SkipForward size={12} /> Skip</button>
                      </>
                    )}
                    <button onClick={() => onOpenOverlap(s.opportunity_id)} className="ml-auto flex items-center gap-1 text-xs font-semibold text-grape hover:underline"><MapPin size={12} /> Open</button>
                  </div>
                </>
              ) : (
                <button onClick={() => onOpenOverlap(s.opportunity_id)} className="mt-0.5 flex items-center gap-1 text-xs font-semibold text-grape hover:underline"><MapPin size={12} /> Open overlap</button>
              )}
            </div>
          );
        })}
      </div>

    </>
  );
}

export function GoalsList({ requests, onBack, onOpen }: { requests: CollabRequest[]; onBack: () => void; onOpen: (id: number) => void }) {
  const [list, setList] = useState<AgentTask[] | null>(null);
  useEffect(() => { goals.list().then(setList).catch(() => setList([])); }, []);
  return (
    <>
      <PanelHeader title="Goals" sub="Multi-step plans Crewly drafted for you" onBack={onBack} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1 overflow-y-auto pr-2">
        {list?.map((t) => {
          const states = t.steps.map((s) => stepState(s, requests));
          const sent = states.filter((s) => s !== "draft" && s !== "skipped").length;
          return (
            <button key={t.id} onClick={() => onOpen(t.id)} className="flex gap-2.5 rounded-2xl px-2 py-2 text-left hover:bg-soft">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-grape-soft text-grape"><Flag size={14} /></span>
              <span className="min-w-0 flex-1">
                <span className="line-clamp-2 text-sm font-semibold leading-snug">{t.goal}</span>
                <span className="text-xs text-muted">{sent} of {t.steps.length} sent · {t.status === "active" ? ago(t.created_at) : t.status}</span>
              </span>
            </button>
          );
        })}
        {list && !list.length && <p className="px-2 py-6 text-center text-sm text-muted">No goals yet. Ask Crewly to "line up our top 5 overlaps".</p>}
        {!list && <p className="text-sm text-muted"><span className="dots">Loading</span></p>}
      </div>
    </>
  );
}
