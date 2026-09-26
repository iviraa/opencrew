import { CircleCheck, CircleDashed, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type IncidentDetail } from "../api";
import { CloseButton, Sheet } from "./ui";

export const INCIDENT_KIND: Record<string, { label: string; color: string }> = {
  downed_line: { label: "Downed line", color: "#ff5d5d" },
  substation_damage: { label: "Substation damage", color: "#7c4dff" },
  outage: { label: "Outage", color: "#ffb020" },
  tree_on_line: { label: "Tree on line", color: "#12a36b" },
  flooding: { label: "Flooding", color: "#2f6bff" },
  tornado: { label: "Tornado damage", color: "#ff4fa3" },
  wind_damage: { label: "Wind damage", color: "#8a94b0" },
};

export const kindColorExpression = ["match", ["get", "kind"], ...Object.entries(INCIDENT_KIND).flatMap(([k, v]) => [k, v.color]), "#8a94b0"];

const ORG = { desc: "DESC", gpc: "Georgia Power" } as Record<string, string>;
const SOURCE: Record<string, { label: string; style: string }> = {
  official: { label: "Official report", style: "bg-save-soft text-save" },
  news: { label: "News", style: "bg-desc-soft text-desc" },
  context: { label: "Context", style: "bg-soft text-muted" },
};

export default function IncidentCard({ id, onClose }: { id: number; onClose: () => void }) {
  const [inc, setInc] = useState<IncidentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setInc(null);
    api.incident(id).then(setInc).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [id]);

  const kind = inc ? INCIDENT_KIND[inc.kind] ?? { label: inc.kind, color: "#8a94b0" } : null;
  const sources = inc?.sources.filter((s) => s.type !== "context").length ?? 0;
  return (
    <Sheet className="max-h-full !h-auto">
      <div className="flex items-start justify-between gap-3 px-5 pb-2 pt-4">
        <div className="min-w-0">
          <div className="display flex items-center gap-2 text-[19px] font-semibold">
            {kind && <span className="h-3.5 w-3.5 shrink-0 rounded-full" style={inc?.verified ? { background: kind.color } : { border: `3px solid ${kind.color}` }} />}
            {kind?.label ?? "Incident"}
          </div>
          {inc && (
            <div className="mt-0.5 text-[13px] text-muted">
              {inc.where_text}, {new Date(inc.ts).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} ET
            </div>
          )}
        </div>
        <CloseButton onClick={onClose} />
      </div>
      {error && <div className="px-5 pb-4 text-[14px] text-[#b42323]">{error}</div>}
      {!inc && !error && <div className="px-5 pb-4 text-[14px] text-muted">Loading the incident…</div>}
      {inc && (
        <div className="thin-scroll space-y-4 overflow-y-auto px-5 pb-5 text-[14px]">
          <div className="flex flex-wrap gap-2">
            {inc.verified
              ? <span className="inline-flex items-center gap-1.5 rounded-full bg-save-soft px-3 py-1 text-[13px] font-semibold text-save"><CircleCheck size={15} /> Verified</span>
              : <span className="inline-flex items-center gap-1.5 rounded-full bg-crew-soft px-3 py-1 text-[13px] font-semibold text-[#9a5b00]"><CircleDashed size={15} /> Needs a second source</span>}
            <span className="rounded-full bg-soft px-3 py-1 text-[13px] text-muted">{Math.round(inc.confidence * 100)}% confident</span>
            <span className="rounded-full bg-soft px-3 py-1 text-[13px] text-muted">located to {inc.precision}</span>
            {inc.customers_affected != null && <span className="rounded-full bg-soft px-3 py-1 text-[13px] text-muted">{inc.customers_affected.toLocaleString()} customers</span>}
            {inc.utility_mentioned && <span className="rounded-full bg-soft px-3 py-1 text-[13px] text-muted">mentions {inc.utility_mentioned}</span>}
          </div>
          {inc.nearest && Object.keys(inc.nearest).length > 0 && (
            <div>
              <h3 className="mb-1.5 text-[15px] font-semibold">Closest utility equipment</h3>
              <div className="space-y-1">
                {Object.entries(inc.nearest).map(([org, a]) => (
                  <div key={org} className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${org === "desc" ? "bg-desc" : "bg-gpc"}`} />
                    <span className="font-semibold">{ORG[org] ?? org}</span><span className="text-muted">{a.asset}, {a.km} km away</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div>
            <h3 className="mb-1.5 text-[15px] font-semibold">Evidence <span className="text-[13px] font-normal text-faint">{sources} {sources === 1 ? "source" : "sources"}</span></h3>
            <ul className="space-y-2">
              {inc.sources.map((s, i) => {
                const src = SOURCE[s.type] ?? { label: s.type, style: "bg-soft text-muted" };
                return (
                  <li key={i} className="rounded-[16px] bg-soft px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[12px] font-semibold ${src.style}`}>{src.label}</span>
                      <span className="font-semibold">{s.name}</span>
                      {s.method === "rules" && <span className="text-[12px] text-faint">found by keyword</span>}
                    </div>
                    {s.url
                      ? <a href={s.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-desc hover:underline">{s.title || s.url}<ExternalLink size={13} /></a>
                      : <div className="mt-1">{s.title}</div>}
                    {s.quote_evidence && <div className="mt-1 text-muted">“{s.quote_evidence}”</div>}
                  </li>
                );
              })}
            </ul>
          </div>
          <p className="text-[12px] text-faint">AI only reads the articles. Places come from a geocoder, and distances and scores from code. News never outranks official reports.</p>
        </div>
      )}
    </Sheet>
  );
}
