import { useEffect, useMemo, useState } from "react";
import { api, type Assumption, type CrewlyAction, type JointPlan as Plan, type PlanConstraints, type ReviewItem, type StormFrame, type JobCollection, type Opportunity, type OpportunityDetail, type Tier } from "./api";
import BriefModal from "./components/BriefModal";
import CrewLanes from "./components/CrewLanes";
import Crewly from "./components/Crewly";
import DetailPanel from "./components/DetailPanel";
import IncidentCard from "./components/IncidentCard";
import IngestModal from "./components/IngestModal";
import JointPlan from "./components/JointPlan";
import PhaseRisks from "./components/PhaseRisks";
import MapView from "./components/MapView";
import OpportunityList from "./components/OpportunityList";
import ReviewPanel from "./components/ReviewPanel";
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
  const [review, setReview] = useState<ReviewItem[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [placingId, setPlacingId] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const [ingestOpen, setIngestOpen] = useState(false);
  const [stormAt, setStormAt] = useState(LANDFALL - 12 * 3600e3);
  const [storm, setStorm] = useState<StormFrame | null>(null);
  const [fly, setFly] = useState<{ bbox: [number, number, number, number]; at: number } | null>(null);
  const [zone, setZone] = useState<GeoJSON.Feature | null>(null);
  const [roadOnly, setRoadOnly] = useState(false);
  const [hover, setHover] = useState<{ key: string; from: "map" | "timeline" } | null>(null);
  const [loading, setLoading] = useState(true);
  const [stormLoading, setStormLoading] = useState(false);
  const [sliders, setSliders] = useState<Record<string, { low: number; high: number }> | null>(null);
  const [listTab, setListTab] = useState<{ tab: string; at: number } | null>(null);
  const [timelineFilter, setTimelineFilter] = useState<{ years: [number, number] | null; orgs: string[] | null } | null>(null);
  const [crewlyBrief, setCrewlyBrief] = useState<{ markdown: string; source: string } | null>(null);
  const [planView, setPlanView] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [solving, setSolving] = useState(false);
  const [pending, setPending] = useState<{ constraints: PlanConstraints; rules: string[] } | null>(null);
  const [liveMode, setLiveMode] = useState(false);
  const [incidentId, setIncidentId] = useState<number | null>(null);
  const [stormTick, setStormTick] = useState(0);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.jobs(horizon), api.opportunities(horizon), api.assumptions()])
      .then(([j, o, a]) => { setJobs(j); setOpps(o); setAssumptions(a); })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [horizon, reload]);

  useEffect(() => {
    if (horizon !== "emergency") { setStorm(null); return; }
    setStormLoading(true);
    const id = setTimeout(() => api.storm(liveMode ? null : stormAt, liveMode ? "live" : "replay").then(setStorm)
      .catch((e) => setError(String(e))).finally(() => setStormLoading(false)), 120);
    return () => clearTimeout(id);
  }, [horizon, stormAt, liveMode, stormTick]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (incidentId != null) setIncidentId(null);  // close the top-most thing only
      else if (ingestOpen) setIngestOpen(false);
      else if (placingId != null) setPlacingId(null);
      else if (crewlyOpen) setCrewlyOpen(false);
      else if (selectedId != null) setSelectedId(null);
      else if (reviewOpen) setReviewOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ingestOpen, placingId, crewlyOpen, selectedId, reviewOpen]);

  useEffect(() => {
    setZone(null);
    if (selectedId == null || horizon === "emergency") return;
    api.driveZone(selectedId).then(setZone).catch(() => {});  // 45 min drive zone around the first site
  }, [selectedId, horizon]);

  useEffect(() => { api.review().then(setReview).catch(() => {}); }, [reload]);

  useEffect(() => {
    if (!planView) return;
    setSolving(true);
    api.plan().then(setPlan).catch((e) => setError(String(e))).finally(() => setSolving(false));
  }, [planView, reload]);

  const solvePlan = (c: PlanConstraints) => {
    setSolving(true);
    api.solvePlan(c).then(setPlan).catch((e) => setError(e instanceof Error ? e.message : String(e))).finally(() => setSolving(false));
  };

  const placeAt = (lon: number, lat: number) => {
    if (placingId == null) return;
    api.place(placingId, lon, lat).then(() => { setPlacingId(null); setReload((n) => n + 1); }).catch((e) => setError(String(e)));
  };

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
  const orgNames = new Map<string, string>();
  jobs?.features.forEach((f) => {
    counts.set(f.properties.org_id, (counts.get(f.properties.org_id) ?? 0) + 1);
    orgNames.set(f.properties.org_id, f.properties.org_name);
  });
  const switchHorizon = (h: string) => {
    setHorizon(h); setSelectedId(null); setCrewlyIds(null);
    if (h === "emergency") setFly({ bbox: [-85.2, 30.6, -79.0, 35.0], at: Date.now() });
  };

  const applyActions = (actions: CrewlyAction[]) => {
    for (const a of actions) {
      if (a.type === "filter") { setHorizon(a.horizon); setTier(a.tier); setCrewlyIds(a.opportunity_ids); }
      if (a.type === "select") { if (a.horizon) setHorizon(a.horizon); setSelectedId(a.opportunity_id); }
      if (a.type === "storm") { setHorizon("emergency"); setLiveMode(false); setStormAt(Date.parse(a.at)); }
      if (a.type === "live") { setHorizon("emergency"); setLiveMode(true); }
      if (a.type === "fly") setFly({ bbox: a.bbox, at: Date.now() });
      if (a.type === "reload") setReload((n) => n + 1);
      if (a.type === "status") { setOpps((xs) => xs.map((o) => (o.id === a.opportunity_id ? { ...o, status: a.status } : o))); setDetail((d) => (d && d.id === a.opportunity_id ? { ...d, status: a.status } : d)); }
      if (a.type === "assumptions") setSliders(a.values);
      if (a.type === "view") { if (a.horizon) switchHorizon(a.horizon); if (a.tier) setTier(a.tier); if (a.tab === "review") setReviewOpen(true); else if (a.tab) { setReviewOpen(false); setListTab({ tab: a.tab, at: Date.now() }); } }
      if (a.type === "timeline") setTimelineFilter({ years: a.years, orgs: a.orgs });
      if (a.type === "brief") { setSelectedId(a.opportunity_id); setCrewlyBrief({ markdown: a.markdown, source: a.source }); }
      if (a.type === "plan") { setReviewOpen(false); setListTab({ tab: "plan", at: Date.now() }); setReload((n) => n + 1); }
      if (a.type === "pending_constraints") { setPending({ constraints: a.constraints, rules: a.rules }); setReviewOpen(false); setListTab({ tab: "plan", at: Date.now() }); }
    }
  };

  const selected = opps.find((o) => o.id === selectedId) ?? null;
  const live = (iso: string) => horizon !== "emergency" || (!liveMode && Date.parse(iso) <= stormAt);  // replay shows what has happened by now; live hides helene jobs
  const shown = useMemo(() => opps.filter((o) => (!tier || o.tier === tier) && (!crewlyIds || crewlyIds.includes(o.id)) && live(o.a_start) && live(o.b_start)
    && (!roadOnly || o.drive_min == null || o.drive_min <= 45)),
    [opps, tier, crewlyIds, horizon, stormAt, roadOnly, liveMode]);  // stable arrays so hover renders don't re-upload map data
  const visibleJobs = useMemo(() => (jobs && horizon === "emergency" ? { ...jobs, features: jobs.features.filter((f) => live(f.properties.start_at)) } : jobs),
    [jobs, horizon, stormAt, liveMode]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-slate-200 bg-white px-5">
        <div className="text-lg font-bold tracking-tight">Open<span className="text-blue-600">Crew</span></div>
        <nav className="flex rounded-lg bg-slate-100 p-0.5">
          {HORIZONS.map((h) => (
            <button key={h.id} disabled={!h.ready} onClick={() => switchHorizon(h.id)}
              className={`whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium ${horizon === h.id ? "bg-white shadow-sm" : "text-slate-500"} disabled:cursor-not-allowed disabled:opacity-50`}>
              {h.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4 whitespace-nowrap text-xs text-slate-500">
          <span>
            {[...counts].map(([org, n], i) => (
              <span key={org} title={orgNames.get(org)}>{i > 0 && " · "}{org.toUpperCase()} <b className="text-slate-800">{n}</b></span>
            ))}{" "}
            {horizon === "near" ? "phases" : horizon === "emergency" ? "restoration jobs" : "projects"}
          </span>
          <span><b className="text-slate-800">{opps.length}</b> opportunities</span>
          {review.length > 0 && (
            <button onClick={() => setReviewOpen((o) => !o)} className="rounded bg-amber-100 px-2 py-0.5 text-amber-800 hover:bg-amber-200"
              title="Projects parsed from filings but not yet placed on the map">{review.length} need location review</button>
          )}
          <button onClick={() => setIngestOpen(true)} className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-200">
            Add filing
          </button>
          <button onClick={() => setCrewlyOpen((o) => !o)}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${crewlyOpen ? "bg-slate-900 text-white" : "bg-blue-600 text-white hover:bg-blue-700"}`}>
            Ask Crewly
          </button>
        </div>
      </header>
      {error && <div className="bg-red-50 px-5 py-2 text-sm text-red-700">{error}</div>}
      {crewlyBrief && <BriefModal markdown={crewlyBrief.markdown} source={crewlyBrief.source} onClose={() => setCrewlyBrief(null)} />}
      {ingestOpen && <IngestModal onClose={() => setIngestOpen(false)} onDone={() => setReload((n) => n + 1)} />}
      <main className="flex min-h-0 flex-1">
        <aside className="w-[380px] shrink-0 border-r border-slate-200 bg-white">
          {reviewOpen
            ? <ReviewPanel items={review} placingId={placingId} onPlace={setPlacingId} onClose={() => { setReviewOpen(false); setPlacingId(null); }} />
            : <OpportunityList items={opps} shown={shown} selectedId={selectedId} tier={tier} onTier={setTier} onSelect={setSelectedId}
            crewlyFiltered={crewlyIds !== null} onClearCrewly={() => setCrewlyIds(null)} loading={loading} roadOnly={roadOnly} onRoadOnly={setRoadOnly} tabRequest={listTab} onTab={(t) => setPlanView(t === "plan")}
            planPanel={<JointPlan plan={plan} solving={solving} onSolve={solvePlan} pending={pending} onDiscardPending={() => setPending(null)} selectedId={selectedId} onSelect={setSelectedId} />}
            emptyText={horizon === "emergency" ? "No cross-utility restoration overlaps yet at this time. Scrub the replay forward." : "No opportunities match these filters."} />}
        </aside>
        <section className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1">
            <MapView jobs={visibleJobs} opportunities={shown} selected={selected} onSelect={setSelectedId} fly={fly} storm={storm} zone={zone} onMapClick={placingId != null ? placeAt : null}
              hoverKey={hover?.key ?? null} onHover={(key) => setHover(key ? { key, from: "map" } : null)} onIncident={setIncidentId} />
            {horizon === "near" && <div className="absolute left-1/2 top-3 z-10 -translate-x-1/2"><PhaseRisks /></div>}
            {incidentId != null && (
              <div className="absolute bottom-3 left-3 top-14 z-30 w-[340px]"><IncidentCard id={incidentId} onClose={() => setIncidentId(null)} /></div>
            )}
            {crewlyOpen && (
              <div className="absolute bottom-3 right-3 top-3 z-20 w-[360px]">
                <Crewly onActions={applyActions} onClose={() => setCrewlyOpen(false)} />
              </div>
            )}
          </div>
          <div className="h-[210px] shrink-0 border-t border-slate-200">
            {planView && horizon === "long" && !reviewOpen
              ? <CrewLanes rows={plan?.schedule ?? []} colors={Object.fromEntries((jobs?.features ?? []).map((f) => [f.properties.org_id, f.properties.color]))}
                  selected={selected ? [selected.job_a, selected.job_b] : []} />
              : horizon === "emergency"
              ? <StormReplay frame={storm} at={stormAt} onAt={setStormAt} start={STORM_START} end={STORM_END} landfall={LANDFALL} loading={stormLoading}
                  live={liveMode} onLive={setLiveMode} onIncident={setIncidentId}
                  onPoll={() => api.livePoll().then(() => setStormTick((n) => n + 1))} />
              : <Timeline jobs={jobs} opportunities={shown} selected={selected} onSelect={setSelectedId} filter={timelineFilter} onClearFilter={() => setTimelineFilter(null)}
                  hoverKey={hover?.key ?? null} scrollToHover={hover?.from === "map"} onHover={(key) => setHover(key ? { key, from: "timeline" } : null)} />}
          </div>
        </section>
        {selectedId != null && (
          <aside className="w-[400px] shrink-0 border-l border-slate-200 bg-white">
            {detail?.id === selectedId
              ? <DetailPanel detail={detail} assumptions={assumptions} onClose={() => setSelectedId(null)} onStatus={setStatus} onRefresh={refreshSelected} overrides={sliders} />
              : <div className="p-4 text-sm text-slate-400">Loading…</div>}
          </aside>
        )}
      </main>
    </div>
  );
}
