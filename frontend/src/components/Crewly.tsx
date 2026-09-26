import DOMPurify from "dompurify";
import { marked } from "marked";
import { ArrowUp, Sparkles, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type CrewlyAction } from "../api";
import { CloseButton, Sheet } from "./ui";

type Message = { role: "user" | "model"; text: string; tools?: { name: string; args: Record<string, unknown> }[]; unsourced?: string[] };

const STARTERS = [
  "What are the top opportunities near Savannah?",
  "Why wasn't Jasper–Okatie shared?",
  "What if cranes cost $150k to $250k a trip?",
  "Draft a brief for the Hooks–Thurmond tie line",
  "Where could both utilities stage crews after Helene?",
];

const TOOL_LABEL: Record<string, string> = {
  find_overlaps: "Searched opportunities", get_opportunity: "Opened a pair", estimate_savings: "Priced savings", search_projects: "Searched projects",
  focus_map: "Moved the map", storm_status: "Checked the storm", find_contacts: "Found contacts", draft_outreach: "Drafted an email",
  find_vendors: "Searched vendors", ingest_filing: "Read a filing", set_status: "Updated status", set_assumptions: "Tried new costs",
  switch_view: "Switched view", project_details: "Looked up a project", review_queue: "Checked unplaced projects", equipment_matches: "Checked equipment",
  compare_projects: "Compared projects", draft_brief: "Wrote a brief", timeline_filter: "Filtered the timeline", propose_constraints: "Suggested rules",
  solve_plan: "Re-planned", compare_plans: "Compared plans", explain_decision: "Explained a decision", incidents_near: "Checked incidents",
  weather_alerts: "Checked weather alerts", phase_weather_risks: "Checked wind at sites",
};

const toolLabel = (t: { name: string; args: Record<string, unknown> }) => {
  const base = TOOL_LABEL[t.name] ?? t.name.replace(/_/g, " ");
  const hint = t.args.region ?? t.args.query ?? t.args.opportunity_id;
  return hint != null ? `${base}: ${typeof hint === "number" ? `#${hint}` : String(hint)}` : base;
};

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
      setMessages([...next, { role: "model", text: `Crewly could not answer: ${e instanceof Error ? e.message : String(e)}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet>
      <div className="flex items-center justify-between px-5 pb-2 pt-4">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-desc text-white shadow-[var(--shadow-desc)]"><Sparkles size={18} /></span>
          <div>
            <div className="display text-[19px] font-semibold leading-tight">Crewly</div>
            <div className="text-[12px] text-muted">Numbers come from OpenCrew's tools</div>
          </div>
        </div>
        <CloseButton onClick={onClose} />
      </div>

      <div className="thin-scroll flex-1 space-y-4 overflow-y-auto px-5 py-3">
        {messages.length === 0 && (
          <div>
            <p className="text-[14.5px] text-muted">Ask about pairs, savings, the joint plan or the storm. Crewly moves the map and list as it works.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {STARTERS.map((s) => (
                <button key={s} onClick={() => send(s)}
                  className="rounded-full bg-desc-soft px-3.5 py-2 text-left text-[13.5px] font-medium text-desc transition hover:bg-[#d6e2ff]">{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "flex justify-end" : ""}>
            {m.role === "user" ? (
              <div className="max-w-[85%] whitespace-pre-wrap rounded-[20px] rounded-br-md bg-desc px-4 py-2.5 text-[14.5px] leading-relaxed text-white">{m.text}</div>
            ) : (
              <div className="space-y-2">
                {m.tools && m.tools.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.tools.map((t, j) => (
                      <span key={j} className="inline-flex items-center gap-1 rounded-full bg-soft px-2.5 py-0.5 text-[12px] text-muted"><Wrench size={11} />{toolLabel(t)}</span>
                    ))}
                  </div>
                )}
                <div className="crewly text-[14.5px] leading-relaxed" dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(marked.parse(m.text) as string) }} />
                {m.unsourced && m.unsourced.length > 0 && (
                  <div className="rounded-[14px] bg-crew-soft px-3 py-2 text-[13px] text-[#9a5b00]">
                    These numbers did not come from a tool, so treat them as unverified: {m.unsourced.join(", ")}.
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-1.5 text-[13px] text-muted" aria-live="polite">
            <span className="flex gap-1">
              {[0, 1, 2].map((k) => <span key={k} className="h-2 w-2 animate-bounce rounded-full bg-desc" style={{ animationDelay: `${k * 0.15}s` }} />)}
            </span>
            Crewly is working…
          </div>
        )}
        <div ref={end} />
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="p-3">
        <div className="flex items-center gap-2 rounded-full bg-soft py-1.5 pl-4 pr-1.5 ring-1 ring-line focus-within:ring-2 focus-within:ring-desc">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask Crewly…" aria-label="Message Crewly"
            className="min-w-0 flex-1 bg-transparent text-[14.5px] outline-none placeholder:text-faint" />
          <button type="submit" disabled={busy || !input.trim()} aria-label="Send"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-desc text-white transition disabled:opacity-40"><ArrowUp size={18} /></button>
        </div>
      </form>
    </Sheet>
  );
}
