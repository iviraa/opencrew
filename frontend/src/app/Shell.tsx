import { Bell, Clock3, LogOut, Radar, UserRound } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Chat, { type ChatMsg } from "./Chat";
import { chatHistory } from "./history";
import Suggestion from "./Suggestion";
import {
  TIER_LABEL, ago, api, company, partnerOf, setCompanies, miles, usd, notices as noticesApi, requests as requestsApi, supabase,
  type CollabRequest, type Jobs, type Me, type Notice, type Overlap, type SuggestionAction,
} from "./data";
import MapPane, { bboxOf, esc, type Bbox, type Fit, type Scene } from "./MapPane";
import { beaver, say } from "./mascot";
import Speech from "./Speech";
import { GoalPanel, GoalsList } from "./GoalPanel";
import { HistoryPanel, OverlapDetailPanel, OverlapList, ProjectList, RequestPanel, sides } from "./panels";
import { NewsTab, Split } from "./tabs";
import HazardsTab, { type HazardFocus } from "./hazards/HazardsTab";
import PlanPanel from "./plan/PlanItems";
import PlanTimeline from "./plan/PlanTimeline";
import type { Chart, Report, Table } from "./generate/types";
import type { Draft } from "./comms/types";
import { planLine, type Horizon } from "./plan/types";
import { usePlans } from "./plan/usePlans";
import { changesOf } from "./findings/changes";
import { FindingPanel, NotebookPanel } from "./findings/Notebook";
import type { Comparison, Finding } from "./findings/types";
import { cardOf, viewsApi, type ViewState } from "./workspace/types";
import ScanOverlay from "./scan/ScanOverlay";
import { RADAR_MS, pop as popAt, useScan } from "./scan/useScan";
import type { RefreshRow } from "./refresh/types";
import MonthGrid from "./maptools/MonthGrid";
import { useMapTools } from "./maptools/useMapTools";

const Beaver = lazy(() => import("./Beaver"));

type Tab = "overlaps" | "weather" | "news";
type Panel = { kind: "overlap"; id: number } | { kind: "request"; id: number } | { kind: "history" } | { kind: "chat" } | { kind: "goal"; id: number } | { kind: "goals" }
  | { kind: "plan"; id: number; item?: string } | { kind: "notebook"; preselect?: number } | { kind: "finding"; id: number; f?: Finding };
const TABS: { id: Tab; label: string }[] = [{ id: "overlaps", label: "Overlaps" }, { id: "weather", label: "Hazards" }, { id: "news", label: "News & damage" }];
const SCAN_STEPS = 5;  // radar step captions live in ScanOverlay
const contextOf = (f: Jobs["features"][number], extra: Record<string, unknown> = {}): GeoJSON.Feature => {  // a scan find, shaped like the context layer's features
  const { id, name, org_id, voltage_kv, geom_quality } = f.properties as { id: string; name: string; org_id: string; voltage_kv?: number | null; geom_quality?: string };
  const org = company(org_id).name;
  return { ...f, properties: { id, name, org_id, org, kv: voltage_kv ?? null, dotted: geom_quality === "county_area" || geom_quality === "approx_area",
    title: `${esc(org)} · ${esc(name)}${voltage_kv ? ` · ${voltage_kv} kV` : ""}`, ...extra } };
};

function feature(f: GeoJSON.Feature, props: Record<string, unknown>): GeoJSON.Feature {
  return { type: "Feature", geometry: f.geometry, properties: props };
}

// a rough circle on the map for a storm field
function circle(lon: number, lat: number, km: number): GeoJSON.Feature {
  const dLat = km / 111, dLon = km / (111 * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: 49 }, (_, i) => { const t = (i / 48) * 2 * Math.PI; return [lon + dLon * Math.cos(t), lat + dLat * Math.sin(t)]; });
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: { color: "#c9184a", opacity: 0.18, title: `<b>Storm scenario</b><br/>${km} km field` } };
}

function mid(line: GeoJSON.LineString): GeoJSON.Point {
  const c = line.coordinates;
  const a = c[0], b = c[c.length - 1];
  return { type: "Point", coordinates: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
}

// "Dominion Energy SC" when there is one neighbor, "3 neighboring utilities" otherwise
function neighbors(os: Overlap[], me: Me) {
  const ids = new Set(os.map((o) => partnerOf(me, o)));
  return ids.size === 1 ? company([...ids][0]).name : `${ids.size} neighboring utilities`;
}

export default function Shell() {
  const [me, setMe] = useState<Me | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overlaps");
  const [projects, setProjects] = useState<Jobs | null>(null);
  const [ov, setOv] = useState<{ overlaps: Overlap[]; jobs: Jobs } | null>(null);
  const [mode, setMode] = useState<"projects" | "scanning" | "overlaps">("projects");
  const [scanStep, setScanStep] = useState(0);
  const scanner = useScan(say);  // the discovery choreography: partners and overlaps first, then other utilities
  const [focus, setFocus] = useState<number[] | null>(null);  // overlaps the chat asked to show
  const [partner, setPartner] = useState<string | null>(null);  // one neighboring utility, or all
  const [selected, setSelected] = useState<number | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [stack, setStack] = useState<Panel[]>([]);
  const [reqs, setReqs] = useState<CollabRequest[]>([]);
  const [notes, setNotes] = useState<Notice[]>([]);
  const [pop, setPop] = useState<"bell" | "profile" | null>(null);
  const [hazardFocus, setHazardFocus] = useState<HazardFocus | null>(null);  // an overlap asking for its weather cost on the hazards tab
  const [overlay, setOverlay] = useState<Finding | null>(null);  // the experiment whose changes the map and lists show
  const [picking, setPicking] = useState(false);  // a finding is waiting for a click on the map
  const [others, setOthers] = useState(true);  // the grey context layer: every other utility's placed projects
  const [context, setContext] = useState<GeoJSON.FeatureCollection | null>(null);
  const contextBox = useRef<Bbox | null>(null);  // the box the context layer was fetched for, padded so panning rarely refetches
  const pickCb = useRef<((lon: number, lat: number) => void) | null>(null);
  const plans = usePlans();  // every plan crewly has built or shown this session
  const [toast, setToast] = useState<{ text: string; request: number } | null>(null);
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [ring, setRing] = useState(0);
  const [memoryTick, setMemoryTick] = useState(0);
  const saved = useRef<number | null>(null);  // how many chat turns are already stored; null until history loads
  const meRef = useRef<Me | null>(null);
  meRef.current = me;

  const top = stack[stack.length - 1] ?? null;
  const push = (p: Panel) => setStack((s) => (s.length && JSON.stringify(s[s.length - 1]) === JSON.stringify(p) ? s : [...s, p]));
  const back = () => setStack((s) => s.slice(0, -1));

  // who am I, my projects, requests and notifications
  useEffect(() => {
    Promise.all([api.me(), api.companies().then(setCompanies).catch(() => {})])  // names and colors for every utility first
      .then(([m]) => { setMe(m); say(`Hi ${m.name}! Want me to find overlaps?`, "wave"); }).catch((e) => setErr(String(e.message ?? e)));
    api.projects().then((p) => {
      setProjects(p);
      const b = bboxOf([p]);
      if (b) setFit({ bbox: b, key: "mine" });  // start on our own service area
    }).catch((e) => setErr(String(e.message ?? e)));
  }, []);

  // saved chat, once per mount; dev strict mode mounts twice, so a stale load is ignored
  useEffect(() => {
    let live = true;
    chatHistory.load().then((h) => {
      if (!live) return;
      saved.current = h.length; setChat((c) => [...h, ...c]);
      if (h.some((m) => m.ids?.length)) api.overlaps().then((d) => setOv((o) => o ?? d)).catch(() => {});  // saved cards need their overlaps
      new Set(h.map((m) => m.plan?.id).filter((x): x is number => x != null)).forEach((id) => plans.load(id).catch(() => {}));  // and saved plan cards their plan
    })
      .catch(() => { if (live) saved.current = 0; });
    return () => { live = false; };
  }, []);

  const reload = useCallback(() => {
    requestsApi.list().then(setReqs).catch(() => {});
    noticesApi.list().then(setNotes).catch(() => {});
  }, []);
  useEffect(reload, [reload]);
  useEffect(() => { api.suggest().then((r) => r.created && reload()).catch(() => {}); }, [reload]);  // crewly looks around once per login

  // live: the other company's requests and answers show up without a refresh
  useEffect(() => {
    if (!me) return;
    const ch = supabase.channel(`crewly-${me.company}`)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "notification", filter: `company_id=eq.${me.company}` }, async (p) => {
        const n = p.new as Notice;
        if (n.kind === "suggestion") {  // quieter than a request: bell and beaver only
          noticesApi.list().then(setNotes).catch(() => {});
          setRing((x) => x + 1);
          say(n.title && n.title.length <= 60 ? `Idea: ${n.title}` : "I have a new idea for you. Check the bell!", "nod");
          return;
        }
        api.suggest().catch(() => {});  // a request or an answer can change what crewly suggests
        const list = await requestsApi.list().catch(() => null);
        if (list) setReqs(list);
        noticesApi.list().then(setNotes).catch(() => {});
        const r = list?.find((x) => x.id === n.request_id);
        const who = r ? company(n.kind === "request" ? r.from_company : r.to_company).name : "A neighboring utility";
        setToast({ request: n.request_id!, text: n.kind === "request" ? `${who} sent you a collaboration request` : `${who} ${n.kind} your request` });
        setRing((x) => x + 1);
        say(n.kind === "request" ? `${who} wants to team up!` : n.kind === "approved" ? `${who} approved our request!` : `${who} declined our request.`,
          n.kind === "declined" ? "sad" : n.kind === "approved" ? "happy" : "surprised");
      })
      .on("postgres_changes", { event: "*", schema: "public", table: "collab_request" }, () => { requestsApi.list().then(setReqs).catch(() => {}); })
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [me]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setPop(null); setToast(null); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(null), 7000); return () => clearTimeout(t); }, [toast]);

  // store finished chat turns so the conversation survives reloads and shows on the company's other devices
  useEffect(() => {
    if (chatBusy || saved.current == null || chat.length <= saved.current) return;
    const fresh = chat.slice(saved.current);
    saved.current = chat.length;
    chatHistory.save(fresh).catch(() => {});
  }, [chat, chatBusy]);

  const clearChat = () => {
    setChat([]); saved.current = 0;
    if (me) chatHistory.clear(me.company).catch(() => {});
  };

  const loadOverlaps = useCallback(async (animate: boolean) => {
    if (!animate) {
      const data = ov ?? await api.overlaps();
      setOv(data); setMode("overlaps");
      return data;
    }
    setMode("scanning"); setScanStep(0); say("I'm looking for overlapping projects.", "thinking");
    return new Promise<{ overlaps: Overlap[]; jobs: Jobs }>((resolve, reject) => scanner.start(meRef.current!, (c) => {
      const data = { overlaps: c.overlaps, jobs: { type: "FeatureCollection" as const, features: [...c.ours.features, ...c.partners.features] } };
      setContext({ type: "FeatureCollection", features: c.others.features.map((f) => contextOf(f)) }); contextBox.current = null;  // the grey layer keeps the scan's finds until the next pan refetches
      setOv(data); setMode("overlaps");
      say(data.overlaps.length ? `Found ${data.overlaps.length} overlaps with ${neighbors(data.overlaps, meRef.current!)}!` : "No overlaps nearby right now.", "happy");
      const b = bboxOf([data.jobs]);
      if (b) setFit({ bbox: b, key: `all${Date.now()}` });
      resolve(data);
    }, reject));
  }, [ov, scanner.start]);

  useEffect(() => {
    if (mode !== "scanning") return;
    const t = setInterval(() => setScanStep((s) => Math.min(s + 1, SCAN_STEPS - 1)), RADAR_MS / SCAN_STEPS);
    return () => clearInterval(t);
  }, [mode]);

  const scan = () => loadOverlaps(true).catch((e) => { setErr(String(e.message ?? e)); setMode("projects"); say("Hmm, I couldn't finish the scan.", "sad"); });

  const openOverlap = useCallback(async (id: number) => {
    setTab("overlaps");
    const data = ov ?? await loadOverlaps(false);
    setMode("overlaps");
    setSelected(id);
    push({ kind: "overlap", id });
    const o = data.overlaps.find((x) => x.id === id);
    if (o) say(o.savings_high > 0 ? `Overlap #${id}: ${miles(o.distance_m)} apart, could save ${usd(o.savings_low)} to ${usd(o.savings_high)}.` : `Overlap #${id}: close by, but built in different years.`, "nod");
    if (o) {
      const jobs = data.jobs.features.filter((f) => f.id === o.job_a || f.id === o.job_b || f.properties.id === o.job_a || f.properties.id === o.job_b);
      const b = bboxOf([{ type: "FeatureCollection", features: [...jobs, { type: "Feature", geometry: o.link, properties: {} }] }]);
      if (b) setFit({ bbox: b, key: `o${id}${Date.now()}`, maxZoom: 11 });
    }
  }, [ov, loadOverlaps]);

  const showIds = useCallback(async (ids: number[]) => {
    setTab("overlaps");
    const data = ov ?? await loadOverlaps(false);
    setMode("overlaps"); setFocus(ids); setSelected(null); setPartner(null);
    const keep = new Set(ids);
    const os = data.overlaps.filter((o) => keep.has(o.id));
    const jobIds = new Set(os.flatMap((o) => [o.job_a, o.job_b]));
    const b = bboxOf([{ type: "FeatureCollection", features: [...data.jobs.features.filter((f) => jobIds.has(f.properties.id)), ...os.map((o) => ({ type: "Feature" as const, geometry: o.link, properties: {} }))] }]);
    if (b) setFit({ bbox: b, key: `f${Date.now()}` });
  }, [ov, loadOverlaps]);

  const sendChat = async (text: string) => {
    const next = [...chat, { role: "user" as const, text }];
    setChat(next); setChatBusy(true); say("Let me check...", "thinking");
    try {
      const r = await api.chat(next.map(({ role, text }) => ({ role, text })));
      const explicit = r.ui_actions.filter((a) => a.type === "show_overlaps").pop();  // crewly named exactly which overlaps to show
      const lists = r.ui_actions.map((a) => a.ids ?? a.opportunity_ids).filter((x): x is number[] => !!x?.length);  // last non-empty list wins
      const open = r.ui_actions.filter((a) => a.type === "open_overlap" || a.type === "select").pop();
      const openId = open ? (open.id ?? open.opportunity_id) : undefined;
      const ids = explicit?.title != null || (explicit && !lists.length) ? (explicit.ids ?? []) : lists.pop() ?? (openId != null ? [openId] : undefined);
      const title = explicit?.title;
      const chart = r.ui_actions.filter((a) => a.type === "chart").pop()?.chart as Chart | undefined;
      const table = r.ui_actions.filter((a) => a.type === "table").pop()?.table as Table | undefined;
      const report = r.ui_actions.filter((a) => a.type === "report").pop()?.report as Report | undefined;
      const finding = r.ui_actions.filter((a) => a.type === "finding").pop()?.finding as Finding | undefined;
      const compare = r.ui_actions.filter((a) => a.type === "compare").pop()?.compare as Comparison | undefined;
      const draft = r.ui_actions.filter((a) => a.type === "draft").pop()?.draft as Draft | undefined;
      const refreshAct = r.ui_actions.filter((a) => a.type === "refresh").pop();
      const refresh = refreshAct ? { rows: refreshAct.refresh as RefreshRow[], ask: !!refreshAct.ask } : undefined;  // planner list updates
      const confirm = r.ui_actions.filter((a) => a.type === "confirm"), goal = r.ui_actions.filter((a) => a.type === "goal").pop()?.id;
      const remembered = r.ui_actions.some((a) => a.type === "memory");
      const acts = r.ui_actions as unknown as ({ type: string } & Record<string, unknown>)[];
      const workspace = acts.map(cardOf).filter((c) => c != null).pop() ?? undefined;  // notes, reminders, pipeline, profile, brief, history, views
      const view = acts.find((a) => a.type === "view"), saveAs = acts.find((a) => a.type === "save_view");
      if (view?.state) applyView(view.state as ViewState);
      if (typeof saveAs?.name === "string") viewsApi.save(saveAs.name, currentView()).then(() => say(`Saved this view as ${saveAs.name}.`, "nod")).catch(() => say("I couldn't save that view.", "sad"));
      const planned = r.ui_actions.filter((a) => a.type === "plan" && a.id != null).pop();
      const plan = planned ? { id: planned.id!, horizon: planned.horizon, item: planned.item } : undefined;
      const cards = mt.cardsOf(r.ui_actions);
      setChat([...next, { role: "model", text: r.reply || "Done.", ids, ...(title && { title }), offline: r.offline, ...(confirm.length && { confirm }), ...(goal != null && { goal }), ...(plan && { plan }),
        ...(chart && { chart }), ...(table && { table }), ...(report && { report }), ...(finding && { finding }), ...(compare && { compare }), ...(draft && { draft }),
        ...(workspace && { workspace }), ...(refresh && { refresh }), ...(cards.length && { cards }) }]);
      if (finding) setOverlay(finding);
      if (remembered) setMemoryTick((t) => t + 1);  // crewly saved or dropped a note
      if (r.offline) say("I'm out of energy for today, sorry!", "sad");
      else if (plan) plans.load(plan.id).then((p) => say(planLine(p, plan.horizon), p.items.length ? "talking" : "nod")).catch(() => say("I built a plan, take a look.", "nod"));
      else if (goal != null) say("Goal set! Check the drafts I wrote.", "happy");
      else if (confirm.length) say("Tap Confirm and I'll do it.", "nod");
      else if (remembered) say("Got it, I'll keep that in mind.", "nod");
      else if (finding) say(finding.title, "talking");  // the card carries the numbers
      else if (compare) say("Here are the two side by side.", "nod");
      else if (draft) say("Draft ready. Edit it, then copy or send.", "nod");
      else if (refresh) say(refresh.ask ? "Apply it from the card when you are sure." : "Here is where the planner lists stand.", "nod");
      else if (workspace) say(workspace.kind === "brief" ? "Here is your week at a glance." : workspace.kind === "reminder" ? "Noted. It will pop up in the bell when due." : "Here you go.", "nod");
      else if (cards.length) say(mt.line(cards) ?? "Here you go.", "nod");
      else if (report) say("Your report is ready. Open it to print or save.", "happy");
      else if (chart) say("Here's your chart.", "nod");
      else if (table) say(`Here are ${table.count} rows, with a CSV download.`, "nod");
      else say(ids && ids.length > 1 ? `I put ${ids.length} overlaps on the map.` : openId != null ? `Here's overlap #${openId}.` : "Here's what I found!");
      if (ids?.length) await showIds(ids);
      if (openId != null) setSelected(openId);
      if (plan?.item) { setTab("overlaps"); push({ kind: "plan", id: plan.id, item: plan.item }); }  // an explained item opens in the panel
      const fly = r.ui_actions.filter((a) => a.type === "fly").pop();
      if (fly?.bbox && !ids?.length) setFit({ bbox: fly.bbox, key: `y${Date.now()}`, maxZoom: 10 });
      await mt.apply(r.ui_actions);  // map_view, highlights, routes and the timeline
    } catch {
      setChat([...next, { role: "model", text: "Sorry, I couldn't reach the server just now. Please try again.", offline: true }]);
      say("I couldn't reach the server.", "sad");
    } finally { setChatBusy(false); }
  };

  const openRequest = (id: number) => {
    push({ kind: "request", id });
    const unread = notes.filter((n) => n.request_id === id && !n.read_at).map((n) => n.id);
    if (unread.length) { noticesApi.markRead(unread).then(() => noticesApi.list().then(setNotes)); }
  };

  // do what a suggestion offers
  const actOn = (n: Notice) => {
    if (!n.read_at) noticesApi.markRead([n.id]).then(() => noticesApi.list().then(setNotes));
    const a = n.action as SuggestionAction;
    if (a.type === "open_request" && a.id != null) { setTab("overlaps"); openRequest(a.id); }
    else if (a.type === "open_overlap" && a.id != null) openOverlap(a.id);
    else if (a.type === "weather") setTab("weather");
    else if (a.type === "plan") { plans.byHorizon((a.horizon as Horizon) ?? "quarter").then((p) => { setTab("overlaps"); push({ kind: "plan", id: p.id }); }).catch(() => {}); }
    else if (a.type === "chat" && a.prompt) { push({ kind: "chat" }); sendChat(a.prompt); }
  };

  const gotRequest = (r: CollabRequest) => setReqs((xs) => [r, ...xs.filter((x) => x.id !== r.id)]);

  // saved views: what is on screen, and putting it back
  const currentView = (): ViewState => ({ tab, partner, focus, selected, bbox: fit?.bbox ?? null });
  const applyView = (v: ViewState) => {
    if (v.tab === "overlaps" || v.tab === "weather" || v.tab === "news") setTab(v.tab);
    if (v.tab === "overlaps" || !v.tab) { if (!ov) loadOverlaps(false).catch(() => {}); setMode("overlaps"); }
    setPartner(v.partner ?? null); setFocus(v.focus ?? null); setSelected(v.selected ?? null);
    if (v.bbox) setFit({ bbox: v.bbox, key: `v${Date.now()}` });
  };
  const openView = async (name: string) => {
    const { data } = await supabase.from("saved_view").select("state").eq("name", name).maybeSingle();
    if (data?.state) { applyView(data.state as ViewState); say(`Back to your ${name} view.`, "nod"); } else say(`I don't have a view called ${name}.`, "sad");
  };
  const unread = notes.filter((n) => !n.read_at).length;

  // ---------- overlaps map ----------
  const visible = useMemo(() => {
    if (!ov) return [];
    const keep = focus ? new Set(focus) : null;
    return ov.overlaps.filter((o) => (!keep || keep.has(o.id)) && (!partner || partnerOf(me!, o) === partner));
  }, [ov, focus, partner, me]);

  const partners = useMemo(() => {  // neighbors with overlaps, most first
    if (!ov || !me) return [];
    const keep = focus ? new Set(focus) : null;
    const n = new Map<string, number>();
    ov.overlaps.filter((o) => !keep || keep.has(o.id)).forEach((o) => n.set(partnerOf(me, o), (n.get(partnerOf(me, o)) ?? 0) + 1));
    return [...n].map(([id, c]) => ({ id, n: c })).sort((a, b) => b.n - a.n);
  }, [ov, focus, me]);

  const scene = useMemo<Scene>(() => {
    if (!me) return {};
    const lines: GeoJSON.Feature[] = [], points: GeoJSON.Feature[] = [];
    const add = (f: GeoJSON.Feature, props: Record<string, unknown>) => (f.geometry?.type === "Point" ? points : lines).push(feature(f, props));
    if (mode !== "overlaps" || !ov) {
      projects?.features.forEach((f) => add(f, { color: me.color, width: 3, radius: 5, opacity: 0.9, title: `<b>${esc(f.properties.name)}</b><br/>${esc(me.name)}` }));
      const c = scanner.ctx;
      if (mode === "scanning" && c) {  // sites pop in as the scan finds them
        const seen = (key: string) => { const at = scanner.revealed.get(key); return at == null ? null : popAt(scanner.now - at); };
        c.partners.features.forEach((f) => { const p = seen(`j:${f.properties.id}`); if (p) add(f, { color: company(f.properties.org_id).color, width: 3 * p.scale, radius: 5 * p.scale, opacity: 0.95 * p.alpha,
          title: `<b>${esc(f.properties.name)}</b><br/>${esc(company(f.properties.org_id).name)}` }); });
        c.overlaps.forEach((o) => { const p = seen(`op:${o.id}`); if (!p) return; const s = sides(me, o);
          const title = `<b>#${o.id} ${esc(TIER_LABEL[o.tier]?.label)}</b><br/>${esc(s.ours.name)}<br/><span style="color:#5e6a8a">with ${esc(s.theirs.name)}</span>`;
          lines.push({ type: "Feature", geometry: o.link, properties: { color: TIER_LABEL[o.tier]?.color, width: 2.5, dash: true, opacity: p.alpha, title } });
          points.push({ type: "Feature", geometry: mid(o.link), properties: { color: TIER_LABEL[o.tier]?.color, radius: 5.5 * p.scale, stroke: "#ffffff", opacity: p.alpha, title } }); });
      }
      return { lines: { type: "FeatureCollection", features: lines }, points: { type: "FeatureCollection", features: points } };
    }
    const sel = selected != null ? ov.overlaps.find((o) => o.id === selected) : null;
    const involved = new Set(visible.flatMap((o) => [o.job_a, o.job_b]));
    const hot = sel ? new Set([sel.job_a, sel.job_b]) : null;
    ov.jobs.features.filter((f) => involved.has(f.properties.id)).forEach((f) => {
      const on = !hot || hot.has(f.properties.id);
      add(f, { color: company(f.properties.org_id).color, width: on && hot ? 5 : 3, radius: on && hot ? 7 : 5, opacity: on ? 0.95 : 0.12,
        title: `<b>${esc(f.properties.name)}</b><br/>${esc(company(f.properties.org_id).name)}` });
    });
    visible.forEach((o) => {
      const on = !sel || sel.id === o.id;
      const s = sides(me, o);
      const title = `<b>#${o.id} ${esc(TIER_LABEL[o.tier]?.label)}</b><br/>${esc(s.ours.name)}<br/><span style="color:#5e6a8a">with ${esc(s.theirs.name)}</span>`;
      lines.push({ type: "Feature", geometry: o.link, properties: { color: TIER_LABEL[o.tier]?.color, width: 2.5, dash: true, opacity: on ? 1 : 0.12, title, pick: `op:${o.id}` } });
      points.push({ type: "Feature", geometry: mid(o.link), properties: { color: TIER_LABEL[o.tier]?.color, radius: sel?.id === o.id ? 9 : 5.5, stroke: sel?.id === o.id ? "#111014" : "#ffffff", opacity: on ? 1 : 0.15, title, pick: `op:${o.id}` } });
    });
    return { lines: { type: "FeatureCollection", features: lines }, points: { type: "FeatureCollection", features: points } };
  }, [me, mode, ov, projects, visible, selected, scanner.ctx, scanner.now, scanner.revealed]);

  const struck = useMemo(() => new Set(changesOf(overlay ?? { kind: "", params: {} } as Finding).filter((c) => c.kind === "exclude_partner").map((c) => String(c.params.partner))), [overlay]);
  const ghosts = useMemo(() => Object.fromEntries(changesOf(overlay ?? { kind: "", params: {} } as Finding).filter((c) => c.kind === "shift_window" && c.params.opportunity_id != null)
    .map((c) => [String(c.params.opportunity_id).replace("#", ""), Number(c.params.months ?? 0)])), [overlay]);
  const shownScene = useMemo<Scene>(() => {  // the experiment's changes drawn over the real map: storm fields, dimmed excluded neighbors
    if (!overlay || !me) return scene;
    const storms = changesOf(overlay).filter((c) => c.kind === "storm").map((c) => {
      const p = (c.params.place ?? {}) as { lon?: number; lat?: number };
      return p.lon != null && p.lat != null ? circle(p.lon, p.lat, Number(c.params.radius_km ?? 80)) : null;
    }).filter((x): x is GeoJSON.Feature => !!x);
    const dim = (fc?: GeoJSON.FeatureCollection) => fc && { ...fc, features: fc.features.map((f) => {
      const pick = String(f.properties?.pick ?? ""), o = pick.startsWith("op:") ? ov?.overlaps.find((x) => x.id === Number(pick.slice(3))) : null;
      return o && struck.has(partnerOf(me, o)) ? { ...f, properties: { ...f.properties, opacity: 0.12 } } : f;
    }) };
    return { areas: { type: "FeatureCollection", features: [...(scene.areas?.features ?? []), ...storms] }, lines: dim(scene.lines), points: dim(scene.points) };
  }, [scene, overlay, struck, ov, me]);
  const pickPlace = (cb: (lon: number, lat: number) => void) => { pickCb.current = cb; setPicking(true); setTab("overlaps"); say("Click a spot on the map.", "nod"); };
  const partnerIds = useMemo(() => partners.map((p) => p.id), [partners]);

  const pickProject = (id: string) => {
    const f = projects?.features.find((x) => x.properties.id === id);
    const b = f && bboxOf([{ type: "FeatureCollection", features: [f] }]);
    if (b) setFit({ bbox: b, key: `p${id}${Date.now()}`, maxZoom: 11 });
    if (f) say(`Here's ${f.properties.name.length > 40 ? `${f.properties.name.slice(0, 40)}...` : f.properties.name}.`, "nod");
  };
  const mt = useMapTools({ me, projects, ov, setTab, setFit, showIds, setPartner, pickProject, openOverlap, setOthers });  // the chat's map, data and explain hand-overs
  const onMove = useCallback((b: Bbox) => {  // fetch the context layer for a box twice the view, only when the view leaves the last one
    const last = contextBox.current;
    if (last && b[0] >= last[0] && b[1] >= last[1] && b[2] <= last[2] && b[3] <= last[3]) return;
    const dx = (b[2] - b[0]) / 2, dy = (b[3] - b[1]) / 2, box: Bbox = [b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy];
    contextBox.current = box;
    api.contextProjects(box).then((fc) => setContext({ ...fc, features: fc.features.map((f) => ({ ...f, properties: { ...f.properties,
      title: `${esc(f.properties.org)} · ${esc(f.properties.name)}${f.properties.kv ? ` · ${f.properties.kv} kV` : ""}` } })) })).catch(() => {});
  }, []);
  const contextShown = useMemo<GeoJSON.FeatureCollection | null>(() => {
    if (!others) return null;
    const c = scanner.ctx;
    if (mode === "scanning" && c) {  // the scan's finds pop into the same grey layer as they are revealed
      const features: GeoJSON.Feature[] = [];
      c.others.features.forEach((f) => { const at = scanner.revealed.get(`j:${f.properties.id}`); if (at != null) features.push(contextOf(f, popAt(scanner.now - at))); });
      return { type: "FeatureCollection", features };
    }
    return context ? { ...context, features: context.features.filter((f) => f.properties?.org_id !== me?.company) } : null;
  }, [others, context, me, mode, scanner.ctx, scanner.now, scanner.revealed]);

  // ---------- right quarter ----------
  const panel = !me || !top ? null : top.kind === "chat" ? (
    <Chat me={me} msgs={chat} busy={chatBusy} overlaps={ov?.overlaps ?? null} requests={reqs} plans={plans} onSend={sendChat} onOpen={openOverlap}
      onDone={gotRequest} onOpenRequest={openRequest} onOpenGoal={(id) => push({ kind: "goal", id })} onOpenPlan={(id, item) => { setTab("overlaps"); push({ kind: "plan", id, item }); }}
      onClose={() => setStack((s) => s.filter((p) => p.kind !== "chat"))} onClear={clearChat} memoryTick={memoryTick}
      partners={partnerIds} onOverlay={setOverlay} onPickPlace={pickPlace} picking={picking} onCompare={(f) => push({ kind: "notebook", preselect: f.id })} onNotebook={() => push({ kind: "notebook" })} onOpenView={openView} mapTools={mt.cardProps} />
  ) : top.kind === "notebook" ? (
    <NotebookPanel onBack={back} preselect={top.preselect} onOpen={(f) => push({ kind: "finding", id: f.id, f })} onCombined={(f) => { setOverlay(f); push({ kind: "finding", id: f.id, f }); }} />
  ) : top.kind === "finding" ? (
    <FindingPanel id={top.id} initial={top.f} onBack={back} partners={partnerIds} onOpen={openOverlap} onOverlay={setOverlay} onPickPlace={pickPlace} picking={picking}
      onCompare={(f) => push({ kind: "notebook", preselect: f.id })} />
  ) : top.kind === "overlap" ? (
    <OverlapDetailPanel me={me} id={top.id} requests={reqs} onBack={() => { back(); setSelected(null); }} onSent={gotRequest} onOpenRequest={openRequest}
      onHazards={(id, m) => { back(); setSelected(null); setHazardFocus({ kind: "zone", id: String(id), period: "month", month: m, at: Date.now() }); setTab("weather"); }} />
  ) : top.kind === "goal" ? (
    <GoalPanel me={me} id={top.id} overlaps={ov?.overlaps ?? null} requests={reqs} onBack={back} onOpenOverlap={openOverlap} onSent={gotRequest} />
  ) : top.kind === "plan" ? (
    <PlanPanel me={me} store={plans} id={top.id} item={top.item} onBack={back} onOpenOverlap={openOverlap} onOpenGoal={(id) => push({ kind: "goal", id })}
      onItem={(item) => setStack((s) => [...s.slice(0, -1), { kind: "plan", id: top.id, ...(item && { item }) }])} onSwitch={(id) => setStack((s) => [...s.slice(0, -1), { kind: "plan", id }])} />
  ) : top.kind === "goals" ? (
    <GoalsList requests={reqs} onBack={back} onOpen={(id) => push({ kind: "goal", id })} />
  ) : top.kind === "request" ? (
    <RequestPanel me={me} id={top.id} requests={reqs} onBack={back} onOpenOverlap={openOverlap} onResponded={gotRequest} />
  ) : (
    <HistoryPanel me={me} requests={reqs} onBack={back} onOpen={openRequest} onGoals={() => push({ kind: "goals" })} onFindings={() => push({ kind: "notebook" })} />
  );

  const overlapsSide = !me ? null : mode === "overlaps" && ov ? (
    <OverlapList me={me} overlaps={visible} requests={reqs} selected={selected} focused={!!focus} onOpen={openOverlap} struck={struck}
      partners={partners} partner={partner} onPartner={(p) => {
        setPartner(p); setSelected(null);
        const os = ov.overlaps.filter((o) => !p || partnerOf(me, o) === p);  // zoom to that neighbor
        const b = bboxOf([{ type: "FeatureCollection", features: os.map((o) => ({ type: "Feature" as const, geometry: o.link, properties: {} })) }]);
        if (b) setFit({ bbox: b, key: `p${p}${Date.now()}` });
        say(p ? `Showing our overlaps with ${company(p).name}.` : "Showing every neighbor again.", "nod");
      }}
      onClearFocus={() => { setFocus(null); say("Showing all our overlaps again.", "nod"); const b = bboxOf([ov.jobs]); if (b) setFit({ bbox: b, key: `all${Date.now()}` }); }} />
  ) : (
    <ProjectList me={me} projects={projects} onPick={pickProject} />
  );

  const chatOpen = top?.kind === "chat";
  const roomy = (n: React.ReactNode) => n && (chatOpen ? n : <div className="flex min-h-0 flex-1 flex-col pb-[60px]">{n}</div>);  // keep lists clear of the chat bubble

  return (
    <div className="relative h-full w-full" onClick={() => pop && setPop(null)}>
      {/* the whiteboard: the purple showing around it is half the gap it used to be, except at the
          bottom, where the board stops just above the white "crewly" wordmark rather than over it */}
      <div className="board absolute bottom-[13vh] left-[2vw] right-[2vw] top-[3.5vh] flex flex-col px-6 pb-5 pt-4">
        <div className="board-frame" />
        <nav className="relative z-10 mb-3 flex items-center gap-6">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => { if (t.id === tab) return; setTab(t.id); if (t.id === "overlaps") say(mode === "overlaps" ? "Back to our overlaps." : "Tap the purple button and I'll look for overlaps.", "nod"); }} className={`relative font-logo text-lg font-semibold ${tab === t.id ? "text-ink" : "text-faint hover:text-muted"}`}>
              {t.label}
              {tab === t.id && (
                <svg className="scribble" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden>
                  <path d="M2 6 C 20 2, 40 9, 60 5 S 90 3, 98 6" fill="none" stroke="#5b2bb5" strokeWidth="3.5" strokeLinecap="round" />
                </svg>
              )}
            </button>
          ))}
          <span className="flex-1" />
          {me && (
            <span className="flex items-center gap-2 rounded-full bg-soft px-3 py-1 text-sm font-semibold">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: me.color }} />{me.name}
            </span>
          )}
        </nav>

        {err && <p className="mb-2 rounded-xl bg-warn-soft px-3 py-2 text-sm text-warn">{err}</p>}

        {me && tab === "overlaps" && top?.kind === "plan" && (  // the plan's timeline takes the map's place while the plan panel is open
          <Split side={roomy(panel)} map={
            <PlanTimeline plan={plans.plans[top.id] ?? null} open={top.item ?? null} busy={plans.busy != null} onBack={back} ghosts={ghosts}
              onOpen={(item) => setStack((s) => [...s.slice(0, -1), { kind: "plan", id: top.id, item }])}
              onRebuild={() => { const p = plans.plans[top.id]; if (p) plans.byHorizon(p.horizon, true).then((np) => { setStack((s) => [...s.slice(0, -1), { kind: "plan", id: np.id }]); say(planLine(np), "nod"); }).catch(() => {}); }} />
          } />
        )}
        {me && tab === "overlaps" && top?.kind !== "plan" && mt.timeline && (  // a timeline from the chat takes the map's place until closed
          <Split side={roomy(panel ?? overlapsSide)} map={<MonthGrid timeline={mt.timeline} onPick={(id, mine) => mt.cardProps.onPickProject?.(id, mine)} onBack={mt.closeTimeline} />} />
        )}
        {me && tab === "overlaps" && top?.kind !== "plan" && !mt.timeline && (
          <Split side={roomy(panel ?? overlapsSide)} map={
            <MapPane scene={mt.decorate(shownScene)} context={contextShown} fit={fit} onMove={onMove} onPick={(p) => p.startsWith("op:") && openOverlap(Number(p.slice(3)))}
              onMapClick={(lon, lat) => { const cb = pickCb.current; if (cb) { pickCb.current = null; setPicking(false); cb(lon, lat); } }}>
              {picking && <div className="pop-in absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-full border-2 border-pen bg-white px-3 py-1 text-xs font-semibold">Click the map to set the place</div>}
              <button onClick={() => setOthers((v) => !v)} aria-pressed={others} title="Other utilities' placed projects, in grey under ours"
                className={`absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-full border-2 px-2.5 py-1 text-xs font-semibold ${others ? "border-pen bg-white" : "border-line bg-white/80 text-muted"}`}>
                <span className="h-2 w-4 rounded-full" style={{ background: others ? "#6b7280" : "#d9dce3" }} />Other utilities{contextShown ? ` · ${contextShown.features.length}` : ""}
              </button>
              {mt.decorated && !overlay && !picking && <button onClick={mt.clear} className="pop-in absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded-full border-2 border-pen bg-white px-3 py-1 text-xs font-semibold hover:bg-grape-soft">Crewly's highlight is on the map · clear</button>}
              {overlay && !picking && (
                <button onClick={() => setOverlay(null)} className="pop-in absolute left-1/2 top-3 z-10 flex -translate-x-1/2 items-center gap-1 rounded-full border-2 border-pen bg-white px-3 py-1 text-xs font-semibold hover:bg-grape-soft">
                  Scenario shown: {changesOf(overlay).length} change{changesOf(overlay).length === 1 ? "" : "s"} · clear
                </button>
              )}
              {mode === "projects" && projects && (
                <div className="pop-in absolute inset-x-0 bottom-6 flex justify-center">
                  <button onClick={scan} className="pen-btn flex items-center gap-2.5 bg-grape px-6 py-3 font-logo text-lg font-semibold text-white">
                    <Radar size={21} /> Find overlaps with nearby projects
                  </button>
                </div>
              )}
              {mode === "scanning" && <ScanOverlay phase={scanner.phase} step={scanStep} counts={scanner.counts} color={me.color} />}
            </MapPane>
          } />
        )}
        {me && tab === "weather" && <HazardsTab me={me} projects={projects} side={roomy(panel)} focus={hazardFocus} control={mt.hazardControl} />}
        {me && tab === "news" && <NewsTab projects={projects} side={roomy(panel)} onOpenOverlap={openOverlap} />}
        {!me && !err && <div className="grid flex-1 place-items-center text-muted"><span className="dots">Getting your projects</span></div>}

        {!chatOpen && me && (
          <button onClick={() => push({ kind: "chat" })} aria-label="Ask Crewly"
            className="pop-in absolute bottom-4 right-5 z-20 grid h-14 w-14 place-items-center rounded-full bg-white transition hover:scale-105">
            <svg viewBox="0 0 64 64" className="h-14 w-14" aria-hidden>
              <path d="M32 6c14.9 0 26 10.3 26 23.5S46.9 53 32 53c-3.4 0-6.6-.5-9.6-1.5L9 57l3.6-11.3C8.4 41.5 6 35.8 6 29.5 6 16.3 17.1 6 32 6z"
                fill="#fff" stroke="#111014" strokeWidth="3.2" strokeLinejoin="round" />
              <circle cx="21" cy="30" r="3.2" fill="#111014" /><circle cx="32" cy="30" r="3.2" fill="#111014" /><circle cx="43" cy="30" r="3.2" fill="#111014" />
            </svg>
          </button>
        )}

        {toast && (
          <div className="pop-in absolute left-1/2 top-[68px] z-30 flex -translate-x-1/2 items-center gap-3 whitespace-nowrap rounded-full border-2 border-pen bg-white py-1.5 pl-4 pr-1.5 shadow-lg" role="status">
            <Bell size={16} className="text-grape" />
            <span className="text-sm font-semibold">{toast.text}</span>
            <button onClick={() => { openRequest(toast.request); setToast(null); }} className="rounded-full bg-grape px-3 py-1 text-sm font-semibold text-white">Open</button>
          </div>
        )}
      </div>

      {/* the beaver and the bottom bar */}
      <Suspense fallback={null}><Beaver className="absolute bottom-[1vh] left-[1vw] z-20 h-[24vh] min-h-[170px] w-[22vh] min-w-[155px]" /></Suspense>
      <div className="font-logo pointer-events-none absolute bottom-[5.5vh] left-[calc(1vw+max(22vh,155px)+8px)] text-[5vh] font-semibold leading-none text-white">crewly</div>
      {/* the beaver fills about four fifths of his canvas, so the last fifth is empty and reads as a gap
          in front of his snout; the bubble tucks back over half of it to sit closer to him */}
      <Speech className="absolute bottom-[calc(10.5vh+12px)] left-[calc(1vw+max(22vh,155px)*0.9+1px)] z-30" />

      <div className="absolute bottom-[4vh] right-[5vw] z-30 flex items-center gap-3.5" onClick={(e) => e.stopPropagation()}>
        <button onClick={() => { setStack((s) => [...s.filter((p) => p.kind !== "history"), { kind: "history" }]); setPop(null); say(reqs.length ? `Here are all ${reqs.length} of our requests.` : "No requests yet. Open an overlap to send one.", "nod"); }} aria-label="Request history"
          className="grid h-[3.5vh] min-h-5.5 w-[3.5vh] min-w-5.5 place-items-center rounded-full bg-[#ece2e6] text-grape transition hover:scale-105">
          <Clock3 className="h-[55%] w-[55%]" strokeWidth={2.5} />
        </button>
        <div className="relative">
          <button onClick={() => { setPop(pop === "bell" ? null : "bell"); if (pop !== "bell") say(unread ? `You have ${unread} new update${unread === 1 ? "" : "s"}.` : "You're all caught up!", "nod"); }} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} className="relative grid place-items-center text-white transition hover:scale-105">
            <Bell key={ring} className={`h-[3.5vh] min-h-5.5 w-[3.5vh] min-w-5.5 ${ring ? "wiggle" : ""}`} fill="white" strokeWidth={1.5} />
            {unread > 0 && <span className="pop-in absolute -right-0.5 -top-0.5 grid h-3 min-w-3 place-items-center rounded-full bg-[#ff1f3d] px-0.5 text-[9px] font-bold text-white">{unread}</span>}
          </button>
          {pop === "bell" && me && (
            <div className="pop-in absolute bottom-[calc(100%+14px)] right-[-60px] w-[340px] rounded-3xl border-2 border-pen bg-white p-3 shadow-xl">
              <div className="mb-1 flex items-center px-1">
                <span className="flex-1 font-logo text-lg font-semibold">Notifications</span>
                {unread > 0 && <button onClick={() => noticesApi.markRead(notes.filter((n) => !n.read_at).map((n) => n.id)).then(reload)} className="text-xs font-semibold text-grape">Mark all read</button>}
              </div>
              <div className="thin-scroll flex max-h-[46vh] flex-col gap-1.5 overflow-y-auto px-0.5 py-0.5">
                {notes.map((n) => {
                  if (n.kind === "suggestion") {
                    return <Suggestion key={n.id} n={n} onAct={() => { setPop(null); actOn(n); }}
                      onDismiss={() => { setNotes((xs) => xs.filter((x) => x.id !== n.id)); noticesApi.dismiss(n.id); }} />;
                  }
                  const r = reqs.find((x) => x.id === n.request_id);
                  const who = r ? company(n.kind === "request" ? r.from_company : r.to_company).name : "A neighboring utility";
                  return (
                    <button key={n.id} onClick={() => { openRequest(n.request_id!); setPop(null); }} className="card-lift flex w-full gap-2.5 px-3 py-2 text-left">
                      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read_at ? "bg-transparent" : "bg-[#ff1f3d]"}`} />
                      <span className="min-w-0">
                        <span className="block text-sm leading-snug">
                          {n.kind === "request" ? <><b>{who}</b> wants to collaborate</> : <><b>{who}</b> {n.kind} your request</>}
                        </span>
                        {r && <span className="line-clamp-1 text-xs text-muted">{n.kind === "request" ? r.summary.theirs : r.summary.ours}</span>}
                        <span className="text-xs text-faint">{ago(n.created_at)}</span>
                      </span>
                    </button>
                  );
                })}
                {!notes.length && <p className="px-2 py-6 text-center text-sm text-muted">Nothing yet. Requests, answers and Crewly's suggestions show up here.</p>}
              </div>
            </div>
          )}
        </div>
        <div className="relative">
          <button onClick={() => setPop(pop === "profile" ? null : "profile")} aria-label="Profile" className="grid h-[4vh] min-h-6 w-[4vh] min-w-6 place-items-center rounded-full border-[1.5px] border-white text-white transition hover:scale-105">
            <UserRound className="h-[62%] w-[62%]" fill="white" strokeWidth={1.2} />
          </button>
          {pop === "profile" && me && (
            <div className="pop-in absolute bottom-[calc(100%+14px)] right-0 w-[260px] rounded-3xl border-2 border-pen bg-white p-4 shadow-xl">
              <div className="flex items-center gap-2.5">
                <span className="grid h-10 w-10 place-items-center rounded-full font-logo text-lg font-semibold text-white" style={{ background: me.color }}>{me.name[0]}</span>
                <span className="min-w-0">
                  <span className="block font-semibold leading-tight">{me.name}</span>
                  <span className="text-sm text-muted">@{me.username}</span>
                </span>
              </div>
              <button onClick={() => { beaver("wave"); supabase.auth.signOut(); }} className="pen-btn mt-4 flex w-full items-center justify-center gap-2 bg-white px-4 py-2 text-sm font-semibold">
                <LogOut size={16} /> Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
