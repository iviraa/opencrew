import { Check, Send, X } from "lucide-react";
import { useState } from "react";
import { company, overlapFor, requests as requestsApi, type ChatAction, type CollabRequest, type Me, type Overlap } from "./data";
import { say } from "./mascot";
import { Card, Chip, Note, Pill, Row } from "./ui";

// what already happened, read from live requests so a reloaded chat never offers the same send twice
function doneState(me: Me, a: ChatAction, reqs: CollabRequest[]) {
  if (a.action === "send_request") {
    const r = reqs.find((x) => x.opportunity_id === a.opportunity_id && x.from_company === me.company && x.status !== "declined");
    return r ? { r, text: r.status === "approved" ? `Approved by ${company(r.to_company).short}` : `Sent to ${company(r.to_company).short}` } : null;
  }
  const r = reqs.find((x) => x.id === a.request_id);
  return r && r.status !== "pending" ? { r, text: r.status === "approved" ? "You approved it" : "You declined it" } : null;
}

export default function Confirm({ me, action, overlaps, requests, onDone, onOpenRequest }: {
  me: Me; action: ChatAction; overlaps: Overlap[] | null; requests: CollabRequest[];
  onDone: (r: CollabRequest) => void; onOpenRequest: (id: number) => void;
}) {
  const send = action.action === "send_request";
  const [text, setText] = useState((send ? action.note : action.feedback) ?? "");
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const done = doneState(me, action, requests);

  const confirm = async () => {
    setBusy(true); setErr(null);
    try {
      const r = send
        ? await requestsApi.send(me, await overlapFor(action.opportunity_id!, overlaps), text)
        : await requestsApi.respond(action.request_id!, action.decision!, text);
      onDone(r);
      say(send ? `Done! Request sent to ${company(r.to_company).name}.` : action.decision === "approved" ? "Approved! I'll let them know." : "Declined. I'll pass on your feedback.",
        send || action.decision === "approved" ? "happy" : "nod");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e)); say("That didn't go through.", "sad");
    } finally { setBusy(false); }
  };

  const decline = !send && action.decision === "declined";
  const icon = send ? <Send size={15} /> : decline ? <X size={15} /> : <Check size={15} />;
  return (
    <Card icon={icon} title={action.label} sub={action.title} busy={busy}
      right={done ? <Chip tone="good" icon={<Check size={11} />}>{done.text}</Chip> : cancelled ? <Chip>Cancelled</Chip> : <Chip tone="amber">Needs your confirm</Chip>}>
      {done ? (
        <Row><Pill onClick={() => onOpenRequest(done.r.id)}>See the request</Pill></Row>
      ) : cancelled ? (
        <Note>Nothing was sent.</Note>
      ) : (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={2000}
            placeholder={send ? "Note for them (optional)" : "Feedback for them (optional)"}
            className="w-full resize-none rounded-xl border-2 border-line px-2.5 py-1.5 text-sm outline-none focus:border-pen" />
          <Row>
            <button onClick={confirm} disabled={busy}
              className={`pen-btn flex flex-1 items-center justify-center gap-1.5 px-3 py-1.5 text-sm font-semibold ${decline ? "bg-white" : send ? "bg-grape text-white" : "bg-save text-white"}`}>
              {icon} {busy ? "Working" : "Confirm"}
            </button>
            <Pill onClick={() => setCancelled(true)} disabled={busy}>Cancel</Pill>
          </Row>
          {err && <Note tone="warn">{err}</Note>}
        </>
      )}
    </Card>
  );
}
