import { useEffect, useState } from "react";
import { api, type Assumption, type JobCollection, type Opportunity, type OpportunityDetail, type Tier } from "./api";
import DetailPanel from "./components/DetailPanel";
import MapView from "./components/MapView";
import OpportunityList from "./components/OpportunityList";
import Timeline from "./components/Timeline";

const HORIZONS = [
  { id: "long", label: "Long-range", ready: true },
  { id: "near", label: "Near-term", ready: true },
  { id: "emergency", label: "Storm replay", ready: false },
];

export default function App() {
  const [horizon, setHorizon] = useState("long");
  const [jobs, setJobs] = useState<JobCollection | null>(null);
  const [opps, setOpps] = useState<Opportunity[]>([]);
  const [assumptions, setAssumptions] = useState<Record<string, Assumption>>({});
  const [tier, setTier] = useState<Tier | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<OpportunityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedId(null);
    Promise.all([api.jobs(horizon), api.opportunities(horizon), api.assumptions()])
      .then(([j, o, a]) => { setJobs(j); setOpps(o); setAssumptions(a); })
      .catch((e) => setError(String(e)));
  }, [horizon]);

  useEffect(() => {
    if (selectedId == null) { setDetail(null); return; }
    api.opportunity(selectedId).then(setDetail).catch((e) => setError(String(e)));
  }, [selectedId]);

  const setStatus = (id: number, status: string) => {
    api.setStatus(id, status).then(() => {
      setOpps((xs) => xs.map((o) => (o.id === id ? { ...o, status } : o)));
      setDetail((d) => (d && d.id === id ? { ...d, status } : d));
    });
  };

  const counts = new Map<string, number>();
  jobs?.features.forEach((f) => counts.set(f.properties.org_name, (counts.get(f.properties.org_name) ?? 0) + 1));
  const selected = opps.find((o) => o.id === selectedId) ?? null;
  const shown = tier ? opps.filter((o) => o.tier === tier) : opps;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-slate-200 bg-white px-5">
        <div className="text-lg font-bold tracking-tight">Open<span className="text-blue-600">Crew</span></div>
        <nav className="flex rounded-lg bg-slate-100 p-0.5">
          {HORIZONS.map((h) => (
            <button key={h.id} disabled={!h.ready} onClick={() => setHorizon(h.id)}
              className={`rounded-md px-3 py-1 text-sm font-medium ${horizon === h.id ? "bg-white shadow-sm" : "text-slate-500"} disabled:cursor-not-allowed disabled:opacity-50`}>
              {h.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4 text-xs text-slate-500">
          {[...counts].map(([org, n]) => <span key={org}>{org}: <b className="text-slate-800">{n}</b> {horizon === "near" ? "phases" : "projects"}</span>)}
          <span>Opportunities: <b className="text-slate-800">{opps.length}</b></span>
        </div>
      </header>
      {error && <div className="bg-red-50 px-5 py-2 text-sm text-red-700">{error}</div>}
      <main className="flex min-h-0 flex-1">
        <aside className="w-[380px] shrink-0 border-r border-slate-200 bg-white">
          <OpportunityList items={opps} selectedId={selectedId} tier={tier} onTier={setTier} onSelect={setSelectedId} />
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <MapView jobs={jobs} opportunities={shown} selected={selected} onSelect={setSelectedId} />
          </div>
          <div className="h-[210px] shrink-0 border-t border-slate-200">
            <Timeline jobs={jobs} opportunities={shown} selected={selected} onSelect={setSelectedId} />
          </div>
        </section>
        {selectedId != null && (
          <aside className="w-[400px] shrink-0 border-l border-slate-200 bg-white">
            {detail?.id === selectedId
              ? <DetailPanel detail={detail} assumptions={assumptions} onClose={() => setSelectedId(null)} onStatus={setStatus} />
              : <div className="p-4 text-sm text-slate-400">Loading…</div>}
          </aside>
        )}
      </main>
    </div>
  );
}
