import { useEffect, useRef, useState } from "react";
import { api, type CrewlyAction } from "../api";

type Message = { role: "user" | "model"; text: string; tools?: { name: string; args: Record<string, unknown> }[]; unsourced?: string[] };

const STARTERS = [
  "What are the top coordination opportunities near Savannah?",
  "Has the Thomson Primary second transformer been delayed?",
  "What if staging yards cost $300k to $600k?",
  "Draft a brief for the Hooks-Thurmond tie line pair",
  "Where could both utilities stage crews 15 hours after Helene's landfall?",
];

export default function Crewly({ onActions, onClose }: { onActions: (a: CrewlyAction[]) => void; onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    const next = [...messages, { role: "user" as const, text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    try {
      const res = await api.crewly(next.map((m) => ({ role: m.role, text: m.text })));
      setMessages([...next, { role: "model", text: res.reply, tools: res.tool_calls, unsourced: res.unsourced }]);
      onActions(res.ui_actions);
    } catch (e) {
      setMessages([...next, { role: "model", text: `Something went wrong: ${e}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col rounded-xl bg-white shadow-2xl ring-1 ring-slate-200">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <div>
          <div className="text-sm font-semibold">Crewly</div>
          <div className="text-[11px] text-slate-500">Numbers come only from OpenCrew tools</div>
        </div>
        <button onClick={onClose} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-xs text-slate-500">Ask about overlaps, savings or a specific project. Crewly updates the map and list as it works.</p>
            {STARTERS.map((s) => (
              <button key={s} onClick={() => send(s)} className="block w-full rounded-lg bg-slate-50 px-3 py-2 text-left text-xs text-slate-700 ring-1 ring-slate-200 hover:bg-slate-100">{s}</button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={m.role === "user" ? "max-w-[85%] rounded-2xl rounded-br-sm bg-blue-600 px-3 py-2 text-white" : "space-y-1.5"}>
              {m.tools && m.tools.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {m.tools.map((t, j) => (
                    <span key={j} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
                      {t.name}({Object.entries(t.args).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", ")})
                    </span>
                  ))}
                </div>
              )}
              <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>
              {m.unsourced && m.unsourced.length > 0 && (
                <div className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800 ring-1 ring-amber-200">
                  Not found in tool results: {m.unsourced.join(", ")}. Treat these as unverified.
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <div className="text-xs text-slate-400">Crewly is working…</div>}
        <div ref={end} />
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="border-t border-slate-200 p-2">
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask Crewly…"
          className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
      </form>
    </div>
  );
}
