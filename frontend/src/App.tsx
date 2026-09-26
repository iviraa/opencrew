import { CalendarDays, ChevronUp, CloudLightning, FilePlus2, MapPinned, MoreHorizontal, Sparkles, X } from "lucide-react";
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
  { id: "long", label: "Plans", hint: "Multi-year construction plans", icon: MapPinned },
  { id: "near", label: "Phases", hint: "Which work phases run at the same time", icon: CalendarDays },
  { id: "emergency", label: "Storm", hint: "Hurricane Helene replay and live weather", icon: CloudLightning },
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
  const [drawer, setDrawer] = useState(false);
  const [menu, setMenu] = useState(false);

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

  const switchHorizon = (h: string) => {
    setHorizon(h); setSelectedId(null); setCrewlyIds(null);
    if (h !== "emergency") setIncidentId(null);  // incident cards belong to the storm view
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

  const lanes = planView && horizon === "long" && !reviewOpen;
  const bottom = horizon === "emergency"
    ? <StormReplay frame={storm} at={stormAt} onAt={setStormAt} start={STORM_START} end={STORM_END} landfall={LANDFALL} loading={stormLoading}
        live={liveMode} onLive={setLiveMode} onIncident={setIncidentId} onPoll={() => api.livePoll().then(() => setStormTick((n) => n + 1))} />
    : lanes
    ? <CrewLanes rows={plan?.schedule ?? []} colors={Object.fromEntries((jobs?.features ?? []).map((f) => [f.properties.org_id, f.properties.color]))}
        selected={selected ? [selected.job_a, selected.job_b] : []} />
    : <Timeline jobs={jobs} opportunities={shown} selected={selected} onSelect={setSelectedId} filter={timelineFilter} onClearFilter={() => setTimelineFilter(null)}
        hoverKey={hover?.key ?? null} scrollToHover={hover?.from === "map"} onHover={(key) => setHover(key ? { key, from: "timeline" } : null)} />;
  const sheetOpen = selectedId != null;

  return (
    <div className="flex h-full flex-col bg-canvas">
      <header className="flex h-16 shrink-0 items-center gap-5 px-5">
        <div className="flex items-center gap-2">
          <span className="relative h-7 w-10" aria-hidden><span className="absolute left-0 top-0.5 h-6 w-6 rounded-full bg-desc" /><span className="absolute right-0 top-0.5 h-6 w-6 rounded-full bg-gpc mix-blend-multiply" /></span>
          <span className="display text-[22px] font-semibold">OpenCrew</span>
        </div>
        <nav className="flex rounded-full bg-surface p-1 shadow-float" aria-label="View">
          {HORIZONS.map((h) => (
            <button key={h.id} onClick={() => switchHorizon(h.id)} title={h.hint} aria-pressed={horizon === h.id}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-[14px] font-semibold transition ${horizon === h.id ? "bg-ink text-white" : "text-muted hover:text-ink"}`}>
              <h.icon size={16} />{h.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <button onClick={() => setMenu((o) => !o)} aria-label="More" aria-expanded={menu}
              className="relative grid h-10 w-10 place-items-center rounded-full bg-surface text-ink shadow-float hover:bg-soft">
              <MoreHorizontal size={20} />
              {review.length > 0 && <span className="absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full bg-crew ring-2 ring-canvas" />}
            </button>
            {menu && (
              <div className="absolute right-0 z-40 mt-2 w-[280px] rounded-[var(--radius-bubble)] bg-surface p-2 shadow-float" onMouseLeave={() => setMenu(false)}>
                <MenuItem icon={<FilePlus2 size={18} />} title="Add a utility filing" hint="Drop in a PDF of planned projects" onClick={() => { setIngestOpen(true); setMenu(false); }} />
                <MenuItem icon={<MapPinned size={18} />} title={`Place ${review.length} projects by hand`} hint="Projects we could not find on the map" onClick={() => { setReviewOpen(true); setMenu(false); }} />
              </div>
            )}
          </div>
          <button onClick={() => setCrewlyOpen((o) => !o)} aria-pressed={crewlyOpen}
            className="inline-flex items-center gap-2 rounded-full bg-desc px-5 py-2.5 text-[15px] font-semibold text-white shadow-desc transition hover:brightness-110">
            <Sparkles size={18} /> Ask Crewly
          </button>
        </div>
      </header>
      {error && (
        <div role="alert" className="fixed left-1/2 top-20 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full bg-ink px-5 py-2.5 text-[14px] text-white shadow-float">
          Something went wrong loading data. Check that the API is running, then try again.
          <button aria-label="Dismiss" onClick={() => setError(null)} className="rounded-full p-1 hover:bg-white/15"><X size={16} /></button>
        </div>
      )}
      {crewlyBrief && <BriefModal markdown={crewlyBrief.markdown} source={crewlyBrief.source} onClose={() => setCrewlyBrief(null)} />}
      {ingestOpen && <IngestModal onClose={() => setIngestOpen(false)} onDone={() => setReload((n) => n + 1)} />}
      <main className="flex min-h-0 flex-1 gap-3 px-3 pb-3">
        <aside className="w-[410px] shrink-0 overflow-hidden rounded-[var(--radius-bubble)] bg-surface shadow-float">
          {reviewOpen
            ? <ReviewPanel items={review} placingId={placingId} onPlace={setPlacingId} onClose={() => { setReviewOpen(false); setPlacingId(null); }} />
            : <OpportunityList items={opps} shown={shown} selectedId={selectedId} tier={tier} onTier={setTier} onSelect={setSelectedId}
            crewlyFiltered={crewlyIds !== null} onClearCrewly={() => setCrewlyIds(null)} loading={loading} roadOnly={roadOnly} onRoadOnly={setRoadOnly} tabRequest={listTab} onTab={(t) => setPlanView(t === "plan")}
            planPanel={<JointPlan plan={plan} solving={solving} onSolve={solvePlan} pending={pending} onDiscardPending={() => setPending(null)} selectedId={selectedId} onSelect={setSelectedId} />}
            emptyText={horizon === "emergency" ? "No restoration team-ups yet at this moment. Move the storm slider forward." : "Try another filter, or clear the one you picked."} />}
        </aside>
        <section className="relative min-w-0 flex-1 overflow-hidden rounded-[var(--radius-bubble)] shadow-float">
          <MapView jobs={visibleJobs} opportunities={shown} selected={selected} onSelect={setSelectedId} fly={fly} storm={storm} zone={zone} onMapClick={placingId != null ? placeAt : null}
            hoverKey={hover?.key ?? null} onHover={(key) => setHover(key ? { key, from: "map" } : null)} onIncident={setIncidentId} />
          {placingId != null && (
            <div className="absolute left-1/2 top-4 z-20 -translate-x-1/2 rounded-full bg-crew px-5 py-2 text-[14px] font-semibold text-ink shadow-float">Click the map where this project is</div>
          )}
          {horizon === "near" && <div className="absolute left-1/2 top-4 z-10 -translate-x-1/2"><PhaseRisks /></div>}
          {incidentId != null && (
            <div className="absolute bottom-3 left-3 top-3 z-30 w-[360px]"><IncidentCard id={incidentId} onClose={() => setIncidentId(null)} /></div>
          )}
          {sheetOpen && (
            <div className="absolute bottom-3 right-3 top-3 z-20 w-[440px] overflow-hidden rounded-[var(--radius-bubble)] bg-surface shadow-float">
              {detail?.id === selectedId
                ? <DetailPanel detail={detail} assumptions={assumptions} onClose={() => setSelectedId(null)} onStatus={setStatus} onRefresh={refreshSelected} overrides={sliders} />
                : <div className="p-6 text-[15px] text-muted">Loading details…</div>}
            </div>
          )}
          {crewlyOpen && (
            <div className={`absolute bottom-3 top-3 z-30 w-[380px] ${sheetOpen ? "right-[456px]" : "right-3"}`}>
              <Crewly onActions={applyActions} onClose={() => setCrewlyOpen(false)} />
            </div>
          )}
          {horizon === "emergency" ? (
            <div className={`absolute bottom-3 left-3 z-10 h-[220px] overflow-hidden rounded-[var(--radius-bubble)] bg-surface shadow-float ${sheetOpen ? "right-[456px]" : "right-3"}`}>{bottom}</div>
          ) : drawer ? (
            <div className={`absolute bottom-3 left-3 z-10 flex h-[260px] flex-col overflow-hidden rounded-[var(--radius-bubble)] bg-surface shadow-float ${sheetOpen ? "right-[456px]" : "right-3"}`}>
              <button onClick={() => setDrawer(false)} className="flex items-center justify-between px-5 pb-1 pt-3 text-left">
                <span className="display text-[16px] font-semibold">{lanes ? "Crew schedule" : "Timeline"}</span>
                <span className="inline-flex items-center gap-1 text-[13px] font-semibold text-muted">Hide <ChevronUp size={16} className="rotate-180" /></span>
              </button>
              <div className="min-h-0 flex-1">{bottom}</div>
            </div>
          ) : (
            <button onClick={() => setDrawer(true)}
              className="absolute bottom-4 left-4 z-10 inline-flex items-center gap-2 rounded-full bg-surface px-5 py-2.5 text-[14px] font-semibold shadow-float hover:bg-soft">
              <ChevronUp size={16} /> {lanes ? "Show crew schedule" : "Show timeline"}
            </button>
          )}
        </section>
      </main>
    </div>
  );
}

function MenuItem({ icon, title, hint, onClick }: { icon: React.ReactNode; title: string; hint: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-start gap-3 rounded-2xl px-3 py-2.5 text-left hover:bg-soft">
      <span className="mt-0.5 text-desc">{icon}</span>
      <span><span className="block text-[14px] font-semibold">{title}</span><span className="block text-[13px] text-muted">{hint}</span></span>
    </button>
  );
}
