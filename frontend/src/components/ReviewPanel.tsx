import type { ReviewItem } from "../api";

type Props = { items: ReviewItem[]; placingId: number | null; onPlace: (id: number | null) => void; onClose: () => void };

export default function ReviewPanel({ items, placingId, onPlace, onClose }: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200 px-4 pb-3 pt-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Location review</h2>
          <button onClick={onClose} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {items.length} projects were parsed from filings but no substation matched with enough confidence. Place one by hand and it joins the overlap engine as "placed by hand".
        </p>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {items.map((it) => (
          <li key={it.id} className={`border-b border-slate-100 px-4 py-2.5 ${placingId === it.id ? "bg-amber-50" : ""}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="text-[13px] leading-5">{it.name}</div>
                <div className="text-[11px] text-slate-500">
                  {it.org_id.toUpperCase()} · in service {it.in_service?.slice(0, 7)} · p.{it.source_page} · looked for: {(it.endpoints ?? []).join(", ")}
                </div>
              </div>
              <button onClick={() => onPlace(placingId === it.id ? null : it.id)}
                className={`shrink-0 rounded px-2 py-1 text-xs font-medium ring-1 ${placingId === it.id ? "bg-amber-500 text-white ring-amber-500" : "bg-white ring-slate-300 hover:bg-slate-100"}`}>
                {placingId === it.id ? "Click map…" : "Place"}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
