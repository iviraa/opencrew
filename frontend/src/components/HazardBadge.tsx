import { Droplets, Wind } from "lucide-react";
import { useEffect, useState } from "react";
import { outlookApi, type JobHazard } from "../api-outlook";

let all: Promise<Record<string, JobHazard>> | null = null;  // one request for every badge on screen
const load = () => (all ??= outlookApi.hazards().catch(() => ({}) as Record<string, JobHazard>));

// Long-range hazard pills for a project: FEMA floodplain and hurricane history. Pass a long-range job id (or a phase's parent id).
export default function HazardBadge({ jobId, detail = false }: { jobId: string; detail?: boolean }) {
  const [h, setH] = useState<JobHazard | null>(null);
  useEffect(() => { let on = true; load().then((m) => on && setH(m[jobId] ?? null)); return () => { on = false; }; }, [jobId]);
  if (!h) return null;
  const tip = h.lines.join("\n");
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap gap-1.5">
        {h.in_floodplain && (
          <span title={tip} className="inline-flex items-center gap-1 rounded-full bg-desc-soft px-2.5 py-0.5 text-[12px] font-semibold text-desc">
            <Droplets size={13} /> In a 100-year floodplain
          </span>
        )}
        {h.in_floodplain === null && detail && (
          <span title={tip} className="inline-flex items-center gap-1 rounded-full bg-soft px-2.5 py-0.5 text-[12px] font-semibold text-muted ring-1 ring-line">
            <Droplets size={13} /> No FEMA flood map
          </span>
        )}
        {(h.hurricane_exposure || detail) && (
          <span title={tip} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${h.hurricane_exposure ? "bg-warn-soft text-warn" : "bg-soft text-muted ring-1 ring-line"}`}>
            <Wind size={13} /> {h.hurricanes_50mi} {h.hurricanes_50mi === 1 ? "hurricane" : "hurricanes"} within 50 mi since {h.since_year}
          </span>
        )}
      </div>
      {detail && (
        <ul className="mt-2 space-y-1 text-[13px] text-muted">
          {h.lines.map((l) => <li key={l}>{l}</li>)}
          <li className="text-[12px] text-faint">Sources: FEMA National Flood Hazard Layer, NOAA HURDAT2 best tracks</li>
        </ul>
      )}
    </div>
  );
}
