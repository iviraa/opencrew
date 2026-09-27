import { Check, Copy, Mail, Paperclip, Send, X } from "lucide-react";
import { useState } from "react";
import { api } from "../data";
import { say } from "../mascot";
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
  return (
    <div className="pop-in rounded-2xl border-2 border-pen bg-white p-2">
      <div className="flex items-start gap-2 px-1">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-grape-soft text-grape"><Mail size={16} /></span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-snug">Email draft to {d.recipient.name}</div>
          <div className="text-[11px] text-faint">{sent ? `Sent ${d.sent_at ? new Date(d.sent_at).toLocaleString() : ""}` : d.status === "copied" ? "Copied, not sent from here" : "Nothing is sent until you confirm"}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-col gap-1.5 px-1">
        <input value={email} onChange={(e) => setEmail(e.target.value)} disabled={sent} placeholder="Recipient email" aria-label="Recipient email"
          className="rounded-xl border-2 border-line px-2.5 py-1 text-xs outline-none focus:border-pen disabled:bg-soft" />
        <input value={subject} onChange={(e) => setSubject(e.target.value)} disabled={sent} aria-label="Subject"
          className="rounded-xl border-2 border-line px-2.5 py-1 text-sm font-semibold outline-none focus:border-pen disabled:bg-soft" />
        <textarea value={body} onChange={(e) => setBody(e.target.value)} disabled={sent} rows={9} aria-label="Body"
          className="thin-scroll w-full resize-y rounded-xl border-2 border-line px-2.5 py-1.5 font-mono text-[12px] leading-snug outline-none focus:border-pen disabled:bg-soft" />
        {d.attachments.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {d.attachments.map((a) => <span key={a.name} className="flex items-center gap-1 rounded-full bg-soft px-2 py-0.5 text-[11px] font-semibold"><Paperclip size={11} /> {a.name}</span>)}
          </div>
        )}
      </div>
      {!sent && (asking ? (
        <div className="mt-2 rounded-xl bg-grape-soft px-2.5 py-2">
          <div className="text-xs font-semibold">Send this email to {email || "no address"}?</div>
          <div className="mt-1.5 flex gap-2">
            <button onClick={send} disabled={busy || !email} className="pen-btn flex flex-1 items-center justify-center gap-1.5 bg-grape px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"><Send size={13} /> {busy ? "..." : "Confirm send"}</button>
            <button onClick={() => setAsking(false)} disabled={busy} className="flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold text-muted hover:text-ink"><X size={13} /> Cancel</button>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex gap-1.5 px-1">
          <button onClick={copy} className="flex flex-1 items-center justify-center gap-1 rounded-full border-2 border-line px-2.5 py-1 text-xs font-semibold hover:border-pen"><Copy size={13} /> Copy</button>
          <button onClick={() => { setNote(null); setAsking(true); }} className="flex flex-1 items-center justify-center gap-1 rounded-full bg-grape px-2.5 py-1 text-xs font-semibold text-white"><Send size={13} /> Send</button>
        </div>
      ))}
      {sent && <div className="mt-2 flex items-center gap-1.5 px-1 text-xs font-semibold text-save"><Check size={14} /> Sent to {d.recipient.email}</div>}
      {note && !sent && <p className="px-1 pt-1.5 text-[11px] text-muted">{note}</p>}
      {err && <p className="px-1 pt-1 text-[11px] text-warn">{err}</p>}
    </div>
  );
}
