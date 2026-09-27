import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { memories, type Memory } from "./history";

// the notes crewly keeps in mind for this company, with a way to drop one
export default function MemoryList({ tick }: { tick: number }) {
  const [rows, setRows] = useState<Memory[] | null>(null);

  useEffect(() => { memories.list().then(setRows).catch(() => setRows([])); }, [tick]);

  const forget = async (id: number) => {
    setRows((r) => r?.filter((m) => m.id !== id) ?? null);
    await memories.forget(id);
  };

  return (
    <div className="pop-in mb-2 rounded-2xl bg-grape-soft/60 px-3 py-2.5">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-grape">Crewly remembers{rows?.length ? ` · ${rows.length}` : ""}</div>
      {rows === null ? <p className="text-xs text-muted"><span className="dots">Loading</span></p> : rows.length ? (
        <div className="flex flex-wrap gap-1.5">
          {rows.map((m) => (
            <span key={m.id} className="flex max-w-full items-center gap-1 rounded-full border-2 border-line bg-white py-0.5 pl-2.5 pr-1 text-xs">
              <span className="min-w-0 truncate" title={m.text}>{m.text}</span>
              <button onClick={() => forget(m.id)} aria-label={`Forget: ${m.text}`} className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-muted hover:bg-soft hover:text-ink"><X size={12} /></button>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-[11px] leading-snug text-muted">Nothing yet. Say something like "remember that we never share crews in hurricane season".</p>
      )}
    </div>
  );
}
