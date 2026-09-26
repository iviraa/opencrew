import { useEffect, useState } from "react";
import { api, type PlanDecisionItem } from "../api";
import { Chip } from "./ui";

export default function PlanDecision({ opportunityId }: { opportunityId: number }) {
  const [d, setD] = useState<PlanDecisionItem | null | undefined>(undefined);
  useEffect(() => {
    setD(undefined);
    api.explainPlan(opportunityId).then((r) => setD(r.decisions[0] ?? null)).catch(() => setD(null));
  }, [opportunityId]);
  if (d === undefined) return <p className="text-[14px] text-faint">Checking the joint plan…</p>;
  if (d === null) return <p className="text-[14px] text-muted">This pair is not part of the latest joint plan. Open the Joint plan tab to solve again.</p>;
  return (
    <div className="rounded-2xl bg-soft px-4 py-3">
      <Chip tone={d.decision === "share" ? "save" : "plain"}>
        {d.decision === "share" ? `Shares ${(d.shared ?? []).join(", ")}` : "Kept separate"}
      </Chip>
      <p className="mt-2 text-[14px] leading-relaxed">{d.sentence}</p>
    </div>
  );
}
