import { RefreshCw, Wind } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type PhaseRisk } from "../api";
import { CloseButton } from "./ui";

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
    return (
      <button onClick={() => setOpen(true)} className="inline-flex items-center gap-1.5 rounded-full bg-surface px-3.5 py-2 text-[13px] font-semibold shadow-float">
        <Wind size={15} className="text-desc" /> Wind at work sites{risks?.length ? ` (${risks.length})` : ""}
      </button>
    );
  }
  return (
    <div className="w-[360px] rounded-[20px] bg-surface px-4 py-3 shadow-float">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[15px] font-semibold"><Wind size={17} className="text-desc" /> Wind at work sites this week</span>
        <span className="flex items-center gap-1">
          <button onClick={poll} disabled={busy} aria-label="Check the forecast now" title="Check the forecast now"
            className="grid h-8 w-8 place-items-center rounded-full text-muted hover:bg-soft hover:text-ink disabled:opacity-50">
            <RefreshCw size={15} className={busy ? "animate-spin" : ""} />
          </button>
          <CloseButton onClick={() => setOpen(false)} />
        </span>
      </div>
      {risks === null && <div className="mt-1 text-[13px] text-muted">Checking the forecast…</div>}
      {risks?.length === 0 && <div className="mt-1 text-[13px] text-muted">No gusts of 35 mph or more forecast at any site with clearing, construction or energization this week.</div>}
      <ul className="thin-scroll mt-2 max-h-32 space-y-1.5 overflow-y-auto">
        {risks?.map((r) => (
          <li key={`${r.job_id}${r.day}`} className="flex items-start gap-2 rounded-[14px] bg-crew-soft px-3 py-2 text-[13px] text-ink">
            <span className="display shrink-0 rounded-full bg-crew px-2 py-0.5 text-[12px] font-semibold text-white">{r.gust_mph} mph</span>
            <span>{r.alert}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
