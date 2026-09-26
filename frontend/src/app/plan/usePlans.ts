import { useCallback, useRef, useState } from "react";
import { api } from "../data";
import type { Horizon, ItemPatch, Plan } from "./types";

export type ExecuteResult = { task_id: number; drafted: number; plan: Plan };
export type PlanStore = {
  plans: Record<number, Plan>;
  busy: number | null;  // the plan being rebuilt or executed
  load: (id: number) => Promise<Plan>;
  byHorizon: (h: Horizon, rebuild?: boolean) => Promise<Plan>;
  patch: (id: number, itemId: string, body: ItemPatch) => Promise<Plan>;
  execute: (id: number) => Promise<ExecuteResult>;
};

// one place that holds every plan the screen has seen, so a chat card, the panel and the timeline show the same thing
export function usePlans(): PlanStore {
  const [plans, setPlans] = useState<Record<number, Plan>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const inflight = useRef<Record<number, Promise<Plan>>>({});
  const keep = useCallback((p: Plan) => { setPlans((ps) => ({ ...ps, [p.id]: p })); return p; }, []);

  const load = useCallback((id: number) => {
    if (!inflight.current[id]) {
      inflight.current[id] = api.get<Plan>(`/api/app/plan/${id}`).then(keep).finally(() => { delete inflight.current[id]; });
    }
    return inflight.current[id];
  }, [keep]);

  const byHorizon = useCallback(async (h: Horizon, rebuild = false) => {
    setBusy(-1);
    try {
      return keep(await (rebuild ? api.send<Plan>(`/api/app/plan/build?horizon=${h}`, "POST") : api.get<Plan>(`/api/app/plan?horizon=${h}`)));
    } finally { setBusy(null); }
  }, [keep]);

  const patch = useCallback(async (id: number, itemId: string, body: ItemPatch) => keep(await api.send<Plan>(`/api/app/plan/${id}/items/${itemId}`, "PATCH", body)), [keep]);

  const execute = useCallback(async (id: number) => {
    setBusy(id);
    try {
      const r = await api.send<ExecuteResult>(`/api/app/plan/${id}/execute`, "POST");
      keep(r.plan);
      return r;
    } finally { setBusy(null); }
  }, [keep]);

  return { plans, busy, load, byHorizon, patch, execute };
}
