import { useEffect, useState } from "react";
import { api, type PlanDecisionItem } from "../api";

export default function PlanDecision({ opportunityId }: { opportunityId: number }) {
  const [d, setD] = useState<PlanDecisionItem | null | undefined>(undefined);
  useEffect(() => {
    setD(undefined);
    api.explainPlan(opportunityId).then((r) => setD(r.decisions[0] ?? null)).catch(() => setD(null));
  }, [opportunityId]);
  if (d === null) return null;  // not in the long-range joint plan
  return (
    <section className="rounded-lg p-3 text-xs ring-1 ring-slate-200">
      <h3 className="mb-1 font-semibold uppercase tracking-wide text-slate-500">Joint plan decision</h3>
      {d === undefined ? <p className="text-slate-400">Checking the joint plan…</p> : (
        <>
          <span className={`rounded px-1.5 py-0.5 font-semibold ${d.decision === "share" ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}>
            {d.decision === "share" ? `Shared ${(d.shared ?? []).join(", ")}` : "Nothing shared"}
          </span>
          <p className="mt-1.5 text-slate-700">{d.sentence}</p>
        </>
      )}
    </section>
  );
}
