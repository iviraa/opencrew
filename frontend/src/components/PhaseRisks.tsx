import { useEffect, useState } from "react";
import { api, type PhaseRisk } from "../api";

export default function PhaseRisks() {
  const [risks, setRisks] = useState<PhaseRisk[] | null>(null);
  const [open, setOpen] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = () => api.phaseRisks().then(setRisks).catch(() => setRisks([]));
  useEffect(() => { load(); }, []);

  const poll = () => {
    setBusy(true);
    api.livePoll().then(load).finally(() => setBusy(false));
  };

  if (!open) {
    return <button onClick={() => setOpen(true)} className="rounded-md bg-white/95 px-2 py-1 text-[11px] font-medium shadow ring-1 ring-slate-200">Wind risk</button>;
  }
  return (
    <div className="w-[360px] rounded-lg bg-white/95 px-3 py-2 text-[11px] shadow-md ring-1 ring-slate-200">
      <div className="flex items-center justify-between">
        <span className="font-semibold">Wind risk at active phases (NWS, next 7 days)</span>
        <span className="flex gap-1">
          <button onClick={poll} disabled={busy} className="rounded bg-slate-100 px-1.5 py-0.5 hover:bg-slate-200 disabled:opacity-50">{busy ? "Checking…" : "Check now"}</button>
          <button onClick={() => setOpen(false)} className="rounded px-1.5 text-slate-400 hover:bg-slate-100">✕</button>
        </span>
      </div>
      {risks === null && <div className="mt-1 text-slate-400">Loading…</div>}
      {risks?.length === 0 && <div className="mt-1 text-slate-500">No forecast gusts at or above 35 mph at sites with clearing, construction or energization this week.</div>}
      <ul className="mt-1 max-h-28 space-y-1 overflow-y-auto">
        {risks?.map((r) => <li key={`${r.job_id}${r.day}`} className="rounded bg-amber-50 px-2 py-1 text-amber-900 ring-1 ring-amber-200">{r.alert}</li>)}
      </ul>
    </div>
  );
}
