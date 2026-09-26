import DOMPurify from "dompurify";
import { marked } from "marked";
import { ArrowUp, CloudOff, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { CollabRequest, Me, Overlap } from "./data";
import { OverlapCard, latestFor } from "./panels";

export type ChatMsg = { role: "user" | "model"; text: string; ids?: number[]; offline?: boolean };

const html = (s: string) => DOMPurify.sanitize(marked.parse(s, { async: false }) as string);

export default function Chat({ me, msgs, busy, overlaps, requests, onSend, onOpen, onClose }: {
  me: Me; msgs: ChatMsg[]; busy: boolean; overlaps: Overlap[] | null; requests: CollabRequest[];
  onSend: (text: string) => void; onOpen: (id: number) => void; onClose: () => void;
}) {
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const byId = new Map((overlaps ?? []).map((o) => [o.id, o]));
  const ideas = [
    `Did ${me.other_name} approve my last request?`,
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
          <div className="text-sm text-muted">Overlaps, requests, weather</div>
        </div>
        <button onClick={onClose} aria-label="Close chat" className="grid h-8 w-8 place-items-center rounded-full border-2 border-pen bg-white hover:bg-grape-soft"><X size={16} strokeWidth={2.5} /></button>
      </div>

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
            {m.ids && m.ids.length > 0 && (
              <div className="flex flex-col gap-1 rounded-2xl border-2 border-line p-1">
                <div className="px-2 pt-1 text-xs font-semibold text-faint">{m.ids.length} on the map · tap one for details</div>
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
