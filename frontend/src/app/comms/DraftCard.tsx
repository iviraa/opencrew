import { Check, Copy, Mail, Paperclip, Send, X } from "lucide-react";
import { useState } from "react";
import { api } from "../data";
import { say } from "../mascot";
import { Card, Chip, Drawer, Note, Pill, Row } from "../ui";
import type { Draft, SendResult } from "./types";

// an email crewly wrote: edit in place, copy it, or send it after an explicit confirm; the server only sends to demo inboxes or allowed domains
export default function DraftCard({ draft: initial }: { draft: Draft }) {
  const [d, setD] = useState(initial);
  const [subject, setSubject] = useState(initial.subject);
  const [body, setBody] = useState(initial.body);
  const [email, setEmail] = useState(initial.recipient.email ?? "");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const dirty = subject !== d.subject || body !== d.body || email !== (d.recipient.email ?? "");

  const save = async () => {
    if (!dirty) return d;
    const row = await api.send<Draft>(`/api/app/comms/draft/${d.id}`, "PATCH", { subject, body, recipient: { ...d.recipient, email: email || null } });
    setD(row); return row;
  };

  const copy = async () => {
    setErr(null);
    try {
      await navigator.clipboard.writeText(`To: ${email || d.recipient.name}\nSubject: ${subject}\n\n${body}`);
      const row = await save();
      if (row.status === "draft") setD(await api.send<Draft>(`/api/app/comms/draft/${d.id}`, "PATCH", { status: "copied" }));
      setNote("Copied. Paste it into your mail client."); say("Copied, it's yours to send.", "nod");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const send = async () => {
    setBusy(true); setErr(null);
    try {
      await save();
      const r = await api.send<SendResult>("/api/app/comms/send", "POST", { id: d.id });
      if (r.draft) setD(r.draft);
      setNote(r.note); setAsking(false);
      say(r.sent ? `Sent to ${email}.` : "I couldn't send that one, but the text is ready to copy.", r.sent ? "happy" : "nod");
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const sent = d.status === "sent";
  const words = body.trim().split(/\s+/).filter(Boolean).length;
  const status = sent ? <Chip tone="good" icon={<Check size={11} />}>Sent{d.sent_at ? ` ${new Date(d.sent_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}` : ""}</Chip>
    : d.status === "copied" ? <Chip tone="info">Copied</Chip> : <Chip>Draft</Chip>;
  const field = "rounded-xl border-2 border-line px-2.5 py-1 outline-none focus:border-pen disabled:bg-soft";
  return (
    <Card icon={<Mail size={15} />} title={`Email to ${d.recipient.name}`} busy={busy}
      sub={<Row>{status}{d.recipient.role && <span>{d.recipient.role}</span>}<span>· {words} words</span>{d.attachments.length > 0 && <span>· {d.attachments.length} attachment{d.attachments.length === 1 ? "" : "s"}</span>}</Row>}>
      <div className="flex flex-col gap-1.5">
        <label className="flex items-center gap-2 text-[11px] text-muted"><span className="w-12 shrink-0">To</span>
          <input value={email} onChange={(e) => setEmail(e.target.value)} disabled={sent} placeholder="Recipient email" aria-label="Recipient email" className={`min-w-0 flex-1 text-xs ${field}`} /></label>
        <label className="flex items-center gap-2 text-[11px] text-muted"><span className="w-12 shrink-0">Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} disabled={sent} aria-label="Subject" className={`min-w-0 flex-1 text-sm font-semibold text-ink ${field}`} /></label>
      </div>
      <Drawer title="Message" summary={body.split("\n").find((l) => l.trim()) ?? ""} defaultOpen>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} disabled={sent} rows={9} aria-label="Body"
          className={`thin-scroll w-full resize-y text-[12px] leading-snug ${field}`} />
        {d.attachments.length > 0 && <Row>{d.attachments.map((a) => <Chip key={a.name} icon={<Paperclip size={11} />}>{a.name}</Chip>)}</Row>}
      </Drawer>
      {!sent && (asking ? (
        <div className="rounded-xl bg-grape-soft px-2.5 py-2">
          <div className="text-xs font-semibold">Send this email to {email || "no address"}?</div>
          <Row className="mt-1.5">
            <button onClick={send} disabled={busy || !email} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-grape px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"><Send size={13} /> {busy ? "Sending" : "Confirm send"}</button>
            <Pill onClick={() => setAsking(false)} disabled={busy} icon={<X size={13} />}>Cancel</Pill>
          </Row>
        </div>
      ) : (
        <Row>
          <Pill grow onClick={copy} icon={<Copy size={13} />}>Copy</Pill>
          <Pill grow primary onClick={() => { setNote(null); setAsking(true); }} icon={<Send size={13} />}>Send</Pill>
        </Row>
      ))}
      {!sent && !asking && <Note>Nothing is sent until you confirm.</Note>}
      {sent && <Note tone="good">Sent to {d.recipient.email}.</Note>}
      {note && !sent && <Note>{note}</Note>}
      {err && <Note tone="warn">{err}</Note>}
    </Card>
  );
}
