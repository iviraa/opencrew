import { useState } from "react";
import { api, type Vendor } from "../api";

const SERVICES = ["Crane rental", "Equipment rental", "Utility contractor"];

export default function Vendors({ opportunityId }: { opportunityId: number }) {
  const [service, setService] = useState<string | null>(null);
  const [items, setItems] = useState<Vendor[]>([]);
  const [note, setNote] = useState<string | null>(null);

  const look = (s: string) => {
    setService(s); setItems([]); setNote("Searching nearby…");
    api.vendors(opportunityId, s.toLowerCase()).then((r) => { setItems(r.vendors); setNote(r.vendors.length ? null : "No vendors found within 40 km."); })
      .catch((e) => setNote(friendly(e instanceof Error ? e.message : String(e))));
  };

  return (
    <div>
      <h4 className="text-[15px] font-semibold">Vendors near the shared site</h4>
      <div className="mt-2 flex flex-wrap gap-2">
        {SERVICES.map((s) => (
          <button key={s} onClick={() => look(s)}
            className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition ${service === s ? "bg-ink text-white" : "bg-soft text-ink ring-1 ring-line hover:bg-white"}`}>{s}</button>
        ))}
      </div>
      {note && <p className="mt-2 text-[13px] text-muted">{note}</p>}
      <ul className="mt-2 space-y-2">
        {items.map((v) => (
          <li key={`${v.name}${v.address}`} className="rounded-2xl bg-soft px-4 py-2.5">
            <div className="flex items-baseline justify-between gap-2"><span className="text-[14px] font-semibold">{v.name}</span><span className="shrink-0 text-[13px] text-muted">{v.distance_km} km</span></div>
            <div className="text-[13px] text-muted">{v.address}</div>
            {v.phone && <div className="text-[13px] text-muted">{v.phone}</div>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function friendly(msg: string) {
  return /GOOGLE_PLACES_KEY/.test(msg) ? "Vendor search needs a Google Places key in the server settings." : msg;
}
