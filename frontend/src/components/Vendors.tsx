import { useState } from "react";
import { api, type Vendor } from "../api";

const SERVICES = ["crane rental", "equipment rental", "utility contractor"];

export default function Vendors({ opportunityId }: { opportunityId: number }) {
  const [service, setService] = useState<string | null>(null);
  const [items, setItems] = useState<Vendor[]>([]);
  const [note, setNote] = useState<string | null>(null);

  const look = (s: string) => {
    setService(s); setItems([]); setNote("Searching…");
    api.vendors(opportunityId, s).then((r) => { setItems(r.vendors); setNote(r.vendors.length ? null : "No vendors within 40 km."); })
      .catch((e) => setNote(e instanceof Error ? e.message : String(e)));
  };

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Vendors near the shared site</h3>
      <div className="flex flex-wrap gap-1.5">
        {SERVICES.map((s) => (
          <button key={s} onClick={() => look(s)}
            className={`rounded px-2 py-1 text-xs font-medium ring-1 ${service === s ? "bg-slate-900 text-white ring-slate-900" : "bg-white ring-slate-300 hover:bg-slate-100"}`}>{s}</button>
        ))}
      </div>
      {note && <p className="mt-2 text-xs text-slate-500">{note}</p>}
      <ul className="mt-2 space-y-1.5">
        {items.map((v) => (
          <li key={`${v.name}${v.address}`} className="rounded bg-slate-50 px-2 py-1.5 text-xs ring-1 ring-slate-200">
            <div className="flex justify-between"><span className="font-medium">{v.name}</span><span className="text-slate-500">{v.distance_km} km</span></div>
            <div className="text-slate-500">{v.address}{v.phone ? ` · ${v.phone}` : ""}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
