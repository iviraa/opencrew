import { useEffect, useState } from "react";
import { api, type ProcurementGroup } from "../api";
import { monthYear } from "../format";
import { Empty } from "./ui";

export default function Procurement() {
  const [groups, setGroups] = useState<ProcurementGroup[] | null>(null);
  useEffect(() => { api.procurement().then(setGroups).catch(() => setGroups([])); }, []);

  return (
    <div className="px-5 pb-6 pt-4">
      <p className="text-[14px] text-muted">
        Equipment both utilities need, of the same kind and voltage. Due within a year of each other: buy together. A planned spare can be shared any year.
      </p>
      {groups === null && <p className="mt-6 text-[14px] text-muted">Looking for matching equipment…</p>}
      {groups?.length === 0 && <Empty title="No equipment matches yet">Adding more filings may turn up shared purchases.</Empty>}
      <div className="mt-4 space-y-3">
        {groups?.map((g) => (
          <article key={g.desc.id} className="rounded-[20px] bg-surface p-4 ring-1 ring-line">
            <div className="flex items-center gap-2">
              <span className="display rounded-full bg-ink px-3 py-0.5 text-[14px] font-semibold text-white">{g.voltage_kv} kV</span>
              <span className="display text-[16px] font-semibold capitalize">{g.kind}</span>
            </div>
            <div className="mt-3 rounded-[14px] bg-desc-soft px-3 py-2">
              <div className="text-[14px] font-semibold">{g.desc.name}</div>
              <div className="text-[13px] text-muted">Dominion Energy SC, in service {monthYear(g.desc.in_service)}</div>
            </div>
            {g.gpc.map((x) => (
              <div key={x.id} className="mt-2 rounded-[14px] bg-gpc-soft px-3 py-2">
                <div className="text-[14px] font-semibold">{x.name}</div>
                <div className="text-[13px] text-muted">Georgia Power, in service {monthYear(x.in_service)}</div>
                <span className="mt-1 inline-block rounded-full bg-surface px-2.5 py-0.5 text-[12px] font-semibold text-warn">{x.reason}</span>
              </div>
            ))}
          </article>
        ))}
      </div>
    </div>
  );
}
