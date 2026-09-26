import { Sparkles, X } from "lucide-react";
import { ago, type Notice, type SuggestionAction } from "./data";

const LABEL: Record<SuggestionAction["type"], string> = { open_request: "Open request", open_overlap: "Open overlap", weather: "See weather", chat: "Ask Crewly" };

// one of crewly's suggestions in the bell: what it noticed, and one thing it can do about it
export default function Suggestion({ n, onAct, onDismiss }: { n: Notice; onAct: () => void; onDismiss: () => void }) {
  return (
    <div className={`flex gap-2.5 rounded-2xl px-2 py-2 ${n.read_at ? "" : "bg-grape-soft/50"}`}>
      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-grape text-white"><Sparkles size={14} /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold leading-snug">{n.title}</span>
        {n.body && <span className="mt-0.5 line-clamp-3 block text-xs text-muted">{n.body}</span>}
        <span className="mt-1.5 flex items-center gap-2">
          {n.action && (
            <button onClick={onAct} className="rounded-full bg-grape px-2.5 py-0.5 text-xs font-semibold text-white hover:bg-grape-deep">{LABEL[n.action.type] ?? "Open"}</button>
          )}
          <span className="text-xs text-faint">Crewly · {ago(n.created_at)}</span>
        </span>
      </span>
      <button onClick={onDismiss} aria-label="Dismiss suggestion" className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-faint hover:bg-soft hover:text-ink"><X size={13} /></button>
    </div>
  );
}
