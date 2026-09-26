import { useEffect, useState } from "react";
import { api, type ProcurementGroup } from "../api";
import { monthYear } from "../format";

export default function Procurement() {
  const [groups, setGroups] = useState<ProcurementGroup[] | null>(null);
  useEffect(() => { api.procurement().then(setGroups); }, []);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3">
      <p className="text-xs text-slate-500">
        Substation equipment of the same kind and voltage class. Due within a year of each other means buy together; a planned spare can be shared any year.
      </p>
      {groups?.length === 0 && <p className="mt-4 text-sm text-slate-500">No matching equipment in the current filings.</p>}
      {groups?.map((g) => (
        <div key={g.desc.id} className="mt-3 rounded-lg border border-slate-200 p-3 text-xs">
          <div className="mb-2 flex items-center gap-2">
            <span className="rounded bg-slate-900 px-1.5 py-0.5 font-semibold text-white">{g.voltage_kv} kV</span>
            <span className="font-medium capitalize">{g.kind}</span>
          </div>
          <div className="border-l-4 border-blue-600 pl-2">
            <div className="font-medium">{g.desc.name}</div>
            <div className="text-slate-500">Dominion Energy SC · in service {monthYear(g.desc.in_service)}</div>
          </div>
          {g.gpc.map((x) => (
            <div key={x.id} className="mt-2 border-l-4 border-red-600 pl-2">
              <div className="font-medium">{x.name}</div>
              <div className="text-slate-500">
                Georgia Power · in service {monthYear(x.in_service)} · <span className="font-medium text-orange-700">{x.reason}</span>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
