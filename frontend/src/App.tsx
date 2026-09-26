import { useEffect, useState } from "react";
import { api, type Assumption, type CrewlyAction, type StormFrame, type JobCollection, type Opportunity, type OpportunityDetail, type Tier } from "./api";
import Crewly from "./components/Crewly";
import DetailPanel from "./components/DetailPanel";
import MapView from "./components/MapView";
import OpportunityList from "./components/OpportunityList";
import StormReplay from "./components/StormReplay";
import Timeline from "./components/Timeline";

const LANDFALL = Date.parse("2024-09-27T03:10:00Z");
const STORM_START = LANDFALL - 72 * 3600e3;
const STORM_END = LANDFALL + 24 * 3600e3;

const HORIZONS = [
  { id: "long", label: "Long-range", ready: true },
  { id: "near", label: "Near-term", ready: true },
  { id: "emergency", label: "Storm replay", ready: true },
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
  const [crewlyOpen, setCrewlyOpen] = useState(false);
  const [crewlyIds, setCrewlyIds] = useState<number[] | null>(null);
  const [review, setReview] = useState(0);
  const [stormAt, setStormAt] = useState(LANDFALL - 12 * 3600e3);
  const [storm, setStorm] = useState<StormFrame | null>(null);
  const [fly, setFly] = useState<{ bbox: [number, number, number, number]; at: number } | null>(null);

  useEffect(() => {
    Promise.all([api.jobs(horizon), api.opportunities(horizon), api.assumptions()])
      .then(([j, o, a]) => { setJobs(j); setOpps(o); setAssumptions(a); })
      .catch((e) => setError(String(e)));
  }, [horizon]);

  useEffect(() => {
    if (horizon !== "emergency") { setStorm(null); return; }
    const id = setTimeout(() => api.storm(stormAt).then(setStorm).catch((e) => setError(String(e))), 120);
    return () => clearTimeout(id);
  }, [horizon, stormAt]);

  useEffect(() => { api.review().then((r) => setReview(r.length)).catch(() => {}); }, []);

  useEffect(() => {
    if (selectedId == null) { setDetail(null); return; }
    api.opportunity(selectedId).then(setDetail).catch((e) => setError(String(e)));
  }, [selectedId]);

  const refreshSelected = () => {
    if (selectedId == null) return;
    api.opportunity(selectedId).then((d) => {
      setDetail(d);
      setOpps((xs) => xs.map((o) => (o.id === d.id ? { ...o, status: d.status } : o)));
    });
  };

  const setStatus = (id: number, status: string) => {
    api.setStatus(id, status).then(() => {
      setOpps((xs) => xs.map((o) => (o.id === id ? { ...o, status } : o)));
      setDetail((d) => (d && d.id === id ? { ...d, status } : d));
    });
  };

  const counts = new Map<string, number>();
  jobs?.features.forEach((f) => counts.set(f.properties.org_name, (counts.get(f.properties.org_name) ?? 0) + 1));
  const switchHorizon = (h: string) => {
    setHorizon(h); setSelectedId(null); setCrewlyIds(null);
    if (h === "emergency") setFly({ bbox: [-85.2, 30.6, -79.0, 35.0], at: Date.now() });
  };

  const applyActions = (actions: CrewlyAction[]) => {
    for (const a of actions) {
      if (a.type === "filter") { setHorizon(a.horizon); setTier(a.tier); setCrewlyIds(a.opportunity_ids); }
      if (a.type === "select") { setHorizon(a.horizon); setSelectedId(a.opportunity_id); }
      if (a.type === "fly") setFly({ bbox: a.bbox, at: Date.now() });
    }
  };

  const selected = opps.find((o) => o.id === selectedId) ?? null;
  const live = (iso: string) => horizon !== "emergency" || Date.parse(iso) <= stormAt;  // storm replay only shows what has happened by now
  const shown = opps.filter((o) => (!tier || o.tier === tier) && (!crewlyIds || crewlyIds.includes(o.id)) && live(o.a_start) && live(o.b_start));
  const visibleJobs = jobs && horizon === "emergency" ? { ...jobs, features: jobs.features.filter((f) => live(f.properties.start_at)) } : jobs;

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-slate-200 bg-white px-5">
        <div className="text-lg font-bold tracking-tight">Open<span className="text-blue-600">Crew</span></div>
        <nav className="flex rounded-lg bg-slate-100 p-0.5">
          {HORIZONS.map((h) => (
            <button key={h.id} disabled={!h.ready} onClick={() => switchHorizon(h.id)}
              className={`rounded-md px-3 py-1 text-sm font-medium ${horizon === h.id ? "bg-white shadow-sm" : "text-slate-500"} disabled:cursor-not-allowed disabled:opacity-50`}>
              {h.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4 text-xs text-slate-500">
          {[...counts].map(([org, n]) => <span key={org}>{org}: <b className="text-slate-800">{n}</b> {horizon === "near" ? "phases" : horizon === "emergency" ? "restoration jobs" : "projects"}</span>)}
          <span>Opportunities: <b className="text-slate-800">{opps.length}</b></span>
          {review > 0 && <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-800" title="Projects parsed from filings but not yet placed on the map">{review} need location review</span>}
          <button onClick={() => setCrewlyOpen((o) => !o)}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${crewlyOpen ? "bg-slate-900 text-white" : "bg-blue-600 text-white hover:bg-blue-700"}`}>
            Ask Crewly
          </button>
        </div>
      </header>
      {error && <div className="bg-red-50 px-5 py-2 text-sm text-red-700">{error}</div>}
      <main className="flex min-h-0 flex-1">
        <aside className="w-[380px] shrink-0 border-r border-slate-200 bg-white">
          <OpportunityList items={opps} shown={shown} selectedId={selectedId} tier={tier} onTier={setTier} onSelect={setSelectedId}
            crewlyFiltered={crewlyIds !== null} onClearCrewly={() => setCrewlyIds(null)} />
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            <MapView jobs={visibleJobs} opportunities={shown} selected={selected} onSelect={setSelectedId} fly={fly} storm={storm} />
            {crewlyOpen && (
              <div className="absolute bottom-3 right-3 top-3 z-20 w-[360px]">
                <Crewly onActions={applyActions} onClose={() => setCrewlyOpen(false)} />
              </div>
            )}
          </div>
          <div className="h-[210px] shrink-0 border-t border-slate-200">
            {horizon === "emergency"
              ? <StormReplay frame={storm} at={stormAt} onAt={setStormAt} start={STORM_START} end={STORM_END} landfall={LANDFALL} />
              : <Timeline jobs={jobs} opportunities={shown} selected={selected} onSelect={setSelectedId} />}
          </div>
        </section>
        {selectedId != null && (
          <aside className="w-[400px] shrink-0 border-l border-slate-200 bg-white">
            {detail?.id === selectedId
              ? <DetailPanel detail={detail} assumptions={assumptions} onClose={() => setSelectedId(null)} onStatus={setStatus} onRefresh={refreshSelected} />
              : <div className="p-4 text-sm text-slate-400">Loading…</div>}
          </aside>
        )}
      </main>
    </div>
  );
}
