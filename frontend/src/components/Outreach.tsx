import { useEffect, useState } from "react";
import { api, type Contact, type OutreachItem } from "../api";

const STATE_STYLE: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700", approved: "bg-blue-100 text-blue-800", sent: "bg-emerald-100 text-emerald-800", replied: "bg-violet-100 text-violet-800",
};

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
    p.then(() => { refresh(); onStatus(); }).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  };

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Start coordination</h3>
      <div className="space-y-1.5">
        {contacts.map((c) => (
          <div key={c.id} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-xs ring-1 ring-slate-200">
            <div>
              <div className="font-medium">{c.org_name}</div>
              <div className="text-slate-500">{c.role} · {c.email ?? "no inbox set"}</div>
            </div>
            <button onClick={() => run(api.draftOutreach(opportunityId, c.id))} className="shrink-0 whitespace-nowrap rounded bg-white px-2 py-1 font-medium ring-1 ring-slate-300 hover:bg-slate-100">
              Draft email
            </button>
          </div>
        ))}
      </div>
      {error && <div className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">{error}</div>}
      <div className="mt-3 space-y-3">
        {items.map((it) => <Draft key={it.id} item={it} run={run} />)}
      </div>
    </section>
  );
}

function Draft({ item, run }: { item: OutreachItem; run: (p: Promise<unknown>) => void }) {
  const [subject, setSubject] = useState(item.subject);
  const [body, setBody] = useState(item.body);
  const [approver, setApprover] = useState("");
  const editable = item.state === "draft";
  const dirty = subject !== item.subject || body !== item.body;

  return (
    <div className="rounded-lg border border-slate-200 p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium">To {item.org_name} · {item.email ?? "no inbox"}</span>
        <span className={`rounded px-1.5 py-0.5 font-semibold ${STATE_STYLE[item.state]}`}>{item.state}</span>
      </div>
      <input value={subject} disabled={!editable} onChange={(e) => setSubject(e.target.value)}
        className="mb-1.5 w-full rounded border border-slate-300 px-2 py-1 font-medium disabled:bg-slate-50" />
      <textarea value={body} disabled={!editable} onChange={(e) => setBody(e.target.value)} rows={9}
        className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-[11px] leading-4 disabled:bg-slate-50" />
      {editable && (
        <div className="mt-2 flex gap-1.5">
          {dirty && <button onClick={() => run(api.editOutreach(item.id, subject, body))} className="rounded bg-slate-100 px-2 py-1 font-medium hover:bg-slate-200">Save edits</button>}
          <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Your name" className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1" />
          <button disabled={!approver.trim() || dirty} onClick={() => run(api.approveOutreach(item.id, approver))}
            className="rounded bg-blue-600 px-2 py-1 font-semibold text-white disabled:opacity-40">Approve</button>
        </div>
      )}
      {item.state === "approved" && (
        <div className="mt-2 flex items-center justify-between">
          <span className="text-slate-500">Approved by {item.approved_by}</span>
          <button onClick={() => run(api.sendOutreach(item.id))} className="rounded bg-emerald-600 px-2 py-1 font-semibold text-white">Send</button>
        </div>
      )}
      {item.state === "sent" && (
        <div className="mt-2 flex items-center justify-between">
          <span className="text-slate-500">Sent {item.sent_at && new Date(item.sent_at).toLocaleString()}</span>
          <button onClick={() => run(api.markReplied(item.id))} className="rounded bg-slate-100 px-2 py-1 font-medium hover:bg-slate-200">Mark replied</button>
        </div>
      )}
      <p className="mt-2 text-[10px] text-slate-400">Nothing is sent until a person approves it. Demo inboxes only.</p>
    </div>
  );
}
