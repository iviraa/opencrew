import { useEffect, useState } from "react";
import { api, type IncidentDetail } from "../api";

export const INCIDENT_KIND: Record<string, { label: string; color: string }> = {
  downed_line: { label: "Downed line", color: "#dc2626" },
  substation_damage: { label: "Substation damage", color: "#7c3aed" },
  outage: { label: "Outage", color: "#f59e0b" },
  tree_on_line: { label: "Tree on line", color: "#16a34a" },
  flooding: { label: "Flooding", color: "#0284c7" },
  tornado: { label: "Tornado damage", color: "#be185d" },
  wind_damage: { label: "Wind damage", color: "#64748b" },
};

export const kindColorExpression = ["match", ["get", "kind"], ...Object.entries(INCIDENT_KIND).flatMap(([k, v]) => [k, v.color]), "#64748b"];

const ORG = { desc: "DESC", gpc: "Georgia Power" } as Record<string, string>;
const SOURCE_STYLE: Record<string, string> = { official: "bg-emerald-100 text-emerald-800", news: "bg-sky-100 text-sky-800", context: "bg-slate-100 text-slate-600" };

export default function IncidentCard({ id, onClose }: { id: number; onClose: () => void }) {
  const [inc, setInc] = useState<IncidentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInc(null);
    api.incident(id).then(setInc).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [id]);

  const kind = inc ? INCIDENT_KIND[inc.kind] ?? { label: inc.kind, color: "#64748b" } : null;
  return (
    <div className="flex max-h-full flex-col rounded-xl bg-white shadow-2xl ring-1 ring-slate-200">
      <div className="flex items-start justify-between border-b border-slate-200 px-4 py-2.5">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold">
            {kind && <span className="h-3 w-3 rounded-full" style={inc?.verified ? { background: kind.color } : { border: `2px solid ${kind.color}` }} />}
            {kind?.label ?? "Incident"}
          </div>
          {inc && <div className="text-[11px] text-slate-500">{inc.where_text} · {new Date(inc.ts).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET</div>}
        </div>
        <button onClick={onClose} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
      </div>
      {error && <div className="p-4 text-xs text-red-700">{error}</div>}
      {!inc && !error && <div className="p-4 text-xs text-slate-400">Loading incident…</div>}
      {inc && (
        <div className="space-y-3 overflow-y-auto px-4 py-3 text-xs">
          <div className="flex flex-wrap gap-1.5">
            <span className={`rounded px-1.5 py-0.5 font-semibold ${inc.verified ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>
              {inc.verified ? "verified" : "unverified · needs confirmation"}
            </span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">confidence {Math.round(inc.confidence * 100)}%</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">location: {inc.precision}</span>
            {inc.customers_affected != null && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{inc.customers_affected.toLocaleString()} customers</span>}
            {inc.utility_mentioned && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">mentions {inc.utility_mentioned}</span>}
          </div>
          {inc.nearest && Object.keys(inc.nearest).length > 0 && (
            <div>
              <div className="mb-1 font-semibold uppercase tracking-wide text-slate-500">Nearest utility assets</div>
              {Object.entries(inc.nearest).map(([org, a]) => (
                <div key={org}>{ORG[org] ?? org}: {a.asset} · {a.km} km</div>
              ))}
            </div>
          )}
          <div>
            <div className="mb-1 font-semibold uppercase tracking-wide text-slate-500">Evidence ({inc.sources.filter((s) => s.type !== "context").length} sources)</div>
            <ul className="space-y-2">
              {inc.sources.map((s, i) => (
                <li key={i} className="rounded bg-slate-50 px-2 py-1.5 ring-1 ring-slate-200">
                  <div className="flex items-center gap-1.5">
                    <span className={`rounded px-1 text-[10px] font-semibold ${SOURCE_STYLE[s.type] ?? "bg-slate-100"}`}>{s.type}</span>
                    <span className="font-medium">{s.name}</span>
                    {s.method === "rules" && <span className="text-[10px] text-slate-400">keyword match</span>}
                  </div>
                  {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">{s.title || s.url}</a> : <div>{s.title}</div>}
                  {s.quote_evidence && <div className="mt-0.5 italic text-slate-600">“{s.quote_evidence}”</div>}
                </li>
              ))}
            </ul>
          </div>
          <p className="text-[10px] text-slate-400">AI only reads text; locations come from geocoding, distances and scores from code. News never overrides official reports.</p>
        </div>
      )}
    </div>
  );
}
