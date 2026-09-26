import { Mail } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type Contact, type OutreachItem } from "../api";
import { Button, Chip } from "./ui";
import { inputClass } from "./ui-extra";

const STATE_LABEL: Record<string, string> = { draft: "Draft", approved: "Approved", sent: "Sent", replied: "Replied" };

export default function Outreach({ opportunityId, onStatus }: { opportunityId: number; onStatus: () => void }) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [items, setItems] = useState<OutreachItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => api.outreach(opportunityId).then(setItems);
  useEffect(() => {
    api.contacts(opportunityId).then(setContacts);
    refresh();
  }, [opportunityId]);

  const run = (p: Promise<unknown>) => {
    setError(null);
    p.then(() => { refresh(); onStatus(); }).catch((e) => setError(friendly(e instanceof Error ? e.message : String(e))));
  };

  return (
    <div>
      <h4 className="text-[15px] font-semibold">Email the planning teams</h4>
      <p className="mt-0.5 text-[13px] text-muted">Drafts are written for you. Nothing is sent until a person approves it.</p>
      <div className="mt-2 space-y-2">
        {contacts.map((c) => (
          <div key={c.id} className="flex items-center justify-between gap-3 rounded-2xl bg-soft px-4 py-2.5">
            <div className="min-w-0">
              <div className="text-[14px] font-semibold">{c.org_name}</div>
              <div className="truncate text-[13px] text-muted">{c.email ?? "No inbox set up yet"}</div>
            </div>
            <Button className="shrink-0 !px-3.5 !py-1.5 !text-[13px]" onClick={() => run(api.draftOutreach(opportunityId, c.id))}><Mail size={15} />Draft</Button>
          </div>
        ))}
      </div>
      {error && <div className="mt-2 rounded-2xl bg-warn-soft px-4 py-2 text-[13px] text-warn">{error}</div>}
      <div className="mt-3 space-y-3">
        {items.map((it) => <Draft key={it.id} item={it} run={run} />)}
      </div>
    </div>
  );
}

function Draft({ item, run }: { item: OutreachItem; run: (p: Promise<unknown>) => void }) {
  const [subject, setSubject] = useState(item.subject);
  const [body, setBody] = useState(item.body);
  const [approver, setApprover] = useState("");
  const editable = item.state === "draft";
  const dirty = subject !== item.subject || body !== item.body;

  return (
    <div className="rounded-2xl bg-surface p-3.5 ring-1 ring-line">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-[14px] font-semibold">To {item.org_name}</span>
        <Chip tone={item.state === "sent" || item.state === "replied" ? "save" : "plain"}>{STATE_LABEL[item.state] ?? item.state}</Chip>
      </div>
      <input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)} aria-label="Subject" className={`${inputClass} font-semibold`} />
      <textarea value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} rows={8} aria-label="Message"
        className={`${inputClass} mt-2 text-[13px] leading-relaxed`} />
      {editable && (
        <div className="mt-2 flex flex-wrap gap-2">
          {dirty && <Button className="!py-1.5 !text-[13px]" onClick={() => run(api.editOutreach(item.id, subject, body))}>Save edits</Button>}
          <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Your name to approve" aria-label="Approver name"
            className={`${inputClass} !w-auto min-w-0 flex-1 !py-1.5`} />
          <Button variant="primary" className="!py-1.5 !text-[13px]" disabled={!approver.trim() || dirty} onClick={() => run(api.approveOutreach(item.id, approver))}>Approve</Button>
        </div>
      )}
      {item.state === "approved" && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[13px] text-muted">Approved by {item.approved_by}</span>
          <Button variant="save" className="!py-1.5 !text-[13px]" onClick={() => run(api.sendOutreach(item.id))}>Send email</Button>
        </div>
      )}
      {item.state === "sent" && (
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[13px] text-muted">Sent {item.sent_at && new Date(item.sent_at).toLocaleString()}</span>
          <Button className="!py-1.5 !text-[13px]" onClick={() => run(api.markReplied(item.id))}>Mark replied</Button>
        </div>
      )}
    </div>
  );
}

function friendly(msg: string) {
  if (/demo inbox/i.test(msg)) return "Sending is limited to demo inboxes, and none is set up yet.";
  if (/RESEND_API_KEY|not configured/i.test(msg)) return "Email sending is not set up yet. The draft is saved and approved.";
  return msg;
}
