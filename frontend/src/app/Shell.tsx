import { Bell, Clock3, LogOut, Radar, UserRound } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Chat, { type ChatMsg } from "./Chat";
import { chatHistory } from "./history";
import Suggestion from "./Suggestion";
import {
  TIER_LABEL, ago, api, company, partnerOf, setCompanies, miles, usd, notices as noticesApi, requests as requestsApi, supabase,
  type CollabRequest, type Jobs, type Me, type Notice, type Overlap, type SuggestionAction,
} from "./data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "./MapPane";
import { beaver, say } from "./mascot";
import Speech from "./Speech";
import { GoalPanel, GoalsList } from "./GoalPanel";
import { HistoryPanel, OverlapDetailPanel, OverlapList, ProjectList, RequestPanel, sides } from "./panels";
import { NewsTab, Split } from "./tabs";
import HazardsTab from "./hazards/HazardsTab";

const Beaver = lazy(() => import("./Beaver"));

type Tab = "overlaps" | "weather" | "news";
type Panel = { kind: "overlap"; id: number } | { kind: "request"; id: number } | { kind: "history" } | { kind: "chat" } | { kind: "goal"; id: number } | { kind: "goals" };
const TABS: { id: Tab; label: string }[] = [{ id: "overlaps", label: "Overlaps" }, { id: "weather", label: "Hazards" }, { id: "news", label: "News & damage" }];
const SCAN_MS = 3200;
const SCAN_STEPS = ["Reading your project plans", "Looking for neighbors within 25 miles", "Measuring drive times", "Comparing build windows", "Estimating savings"];

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function feature(f: GeoJSON.Feature, props: Record<string, unknown>): GeoJSON.Feature {
  return { type: "Feature", geometry: f.geometry, properties: props };
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
  const [focus, setFocus] = useState<number[] | null>(null);  // overlaps the chat asked to show
  const [partner, setPartner] = useState<string | null>(null);  // one neighboring utility, or all
  const [selected, setSelected] = useState<number | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [stack, setStack] = useState<Panel[]>([]);
  const [reqs, setReqs] = useState<CollabRequest[]>([]);
  const [notes, setNotes] = useState<Notice[]>([]);
  const [pop, setPop] = useState<"bell" | "profile" | null>(null);
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
    if (animate) { setMode("scanning"); setScanStep(0); say("I'm looking for overlapping projects.", "thinking"); }
    const [data] = await Promise.all([ov ? Promise.resolve(ov) : api.overlaps(), animate ? wait(SCAN_MS) : null]);
    setOv(data); setMode("overlaps");
    if (animate) {
      say(data.overlaps.length ? `Found ${data.overlaps.length} overlaps with ${neighbors(data.overlaps, meRef.current!)}!` : "No overlaps nearby right now.", "happy");
      const b = bboxOf([data.jobs]);
      if (b) setFit({ bbox: b, key: `all${Date.now()}` });
    }
    return data;
  }, [ov]);

  useEffect(() => {
    if (mode !== "scanning") return;
    const t = setInterval(() => setScanStep((s) => Math.min(s + 1, SCAN_STEPS.length - 1)), SCAN_MS / SCAN_STEPS.length);
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
      const lists = r.ui_actions.map((a) => a.ids ?? a.opportunity_ids).filter((x): x is number[] => !!x?.length);  // last non-empty list wins
      const open = r.ui_actions.filter((a) => a.type === "open_overlap" || a.type === "select").pop();
      const openId = open ? (open.id ?? open.opportunity_id) : undefined;
      const ids = lists.pop() ?? (openId != null ? [openId] : undefined);
      const confirm = r.ui_actions.filter((a) => a.type === "confirm"), goal = r.ui_actions.filter((a) => a.type === "goal").pop()?.id;
      const remembered = r.ui_actions.some((a) => a.type === "memory");
      setChat([...next, { role: "model", text: r.reply || "Done.", ids, offline: r.offline, ...(confirm.length && { confirm }), ...(goal != null && { goal }) }]);
      if (remembered) setMemoryTick((t) => t + 1);  // crewly saved or dropped a note
      if (r.offline) say("I'm out of energy for today, sorry!", "sad");
      else if (goal != null) say("Goal set! Check the drafts I wrote.", "happy");
      else if (confirm.length) say("Tap Confirm and I'll do it.", "nod");
      else if (remembered) say("Got it, I'll keep that in mind.", "nod");
      else say(ids && ids.length > 1 ? `I put ${ids.length} overlaps on the map.` : openId != null ? `Here's overlap #${openId}.` : "Here's what I found!");
      if (ids?.length) await showIds(ids);
      if (openId != null) setSelected(openId);
      const fly = r.ui_actions.filter((a) => a.type === "fly").pop();
      if (fly?.bbox && !ids?.length) setFit({ bbox: fly.bbox, key: `y${Date.now()}`, maxZoom: 10 });
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
    else if (a.type === "chat" && a.prompt) { push({ kind: "chat" }); sendChat(a.prompt); }
  };

  const gotRequest = (r: CollabRequest) => setReqs((xs) => [r, ...xs.filter((x) => x.id !== r.id)]);
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
      projects?.features.forEach((f) => add(f, { color: me.color, width: 3, radius: 5, opacity: mode === "scanning" ? 0.5 : 0.9,
        title: `<b>${esc(f.properties.name)}</b><br/>${esc(me.name)}` }));
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
  }, [me, mode, ov, projects, visible, selected]);

  const pickProject = (id: string) => {
    const f = projects?.features.find((x) => x.properties.id === id);
    const b = f && bboxOf([{ type: "FeatureCollection", features: [f] }]);
    if (b) setFit({ bbox: b, key: `p${id}${Date.now()}`, maxZoom: 11 });
    if (f) say(`Here's ${f.properties.name.length > 40 ? `${f.properties.name.slice(0, 40)}...` : f.properties.name}.`, "nod");
  };

  // ---------- right quarter ----------
  const panel = !me || !top ? null : top.kind === "chat" ? (
    <Chat me={me} msgs={chat} busy={chatBusy} overlaps={ov?.overlaps ?? null} requests={reqs} onSend={sendChat} onOpen={openOverlap}
      onDone={gotRequest} onOpenRequest={openRequest} onOpenGoal={(id) => push({ kind: "goal", id })}
      onClose={() => setStack((s) => s.filter((p) => p.kind !== "chat"))} onClear={clearChat} memoryTick={memoryTick} />
  ) : top.kind === "overlap" ? (
    <OverlapDetailPanel me={me} id={top.id} requests={reqs} onBack={() => { back(); setSelected(null); }} onSent={gotRequest} onOpenRequest={openRequest} />
  ) : top.kind === "goal" ? (
    <GoalPanel me={me} id={top.id} overlaps={ov?.overlaps ?? null} requests={reqs} onBack={back} onOpenOverlap={openOverlap} onSent={gotRequest} />
  ) : top.kind === "goals" ? (
    <GoalsList requests={reqs} onBack={back} onOpen={(id) => push({ kind: "goal", id })} />
  ) : top.kind === "request" ? (
    <RequestPanel me={me} id={top.id} requests={reqs} onBack={back} onOpenOverlap={openOverlap} onResponded={gotRequest} />
  ) : (
    <HistoryPanel me={me} requests={reqs} onBack={back} onOpen={openRequest} onGoals={() => push({ kind: "goals" })} />
  );

  const overlapsSide = !me ? null : mode === "overlaps" && ov ? (
    <OverlapList me={me} overlaps={visible} requests={reqs} selected={selected} focused={!!focus} onOpen={openOverlap}
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
      {/* the whiteboard */}
      <div className="board absolute bottom-[17vh] left-[4vw] right-[4vw] top-[7vh] flex flex-col px-6 pb-5 pt-4">
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

        {me && tab === "overlaps" && (
          <Split side={roomy(panel ?? overlapsSide)} map={
            <MapPane scene={scene} fit={fit} onPick={(p) => p.startsWith("op:") && openOverlap(Number(p.slice(3)))}>
              {mode === "projects" && projects && (
                <div className="pop-in absolute inset-x-0 bottom-6 flex justify-center">
                  <button onClick={scan} className="pen-btn flex items-center gap-2.5 bg-grape px-6 py-3 font-logo text-lg font-semibold text-white">
                    <Radar size={21} /> Find overlaps with nearby projects
                  </button>
                </div>
              )}
              {mode === "scanning" && (
                <div className="absolute inset-0 grid place-items-center bg-white/55 backdrop-blur-[2px]">
                  <div className="pop-in flex flex-col items-center gap-5">
                    <div className="radar">
                      <span className="radar-ring" /><span className="radar-ring" style={{ animationDelay: ".8s" }} /><span className="radar-ring" style={{ animationDelay: "1.6s" }} />
                      <span className="blip" style={{ left: "64%", top: "30%", background: "#ff9f1c" }} />
                      <span className="blip" style={{ left: "28%", top: "58%", background: me.color, animationDelay: ".5s" }} />
                      <span className="blip" style={{ left: "52%", top: "72%", background: "#00b8a9", animationDelay: "1s" }} />
                    </div>
                    <div className="text-center">
                      <div className="font-logo text-2xl font-semibold"><span className="dots">Scanning for nearby projects</span></div>
                      <div key={scanStep} className="pop-in mt-1 text-sm text-muted">{SCAN_STEPS[scanStep]}</div>
                    </div>
                  </div>
                </div>
              )}
            </MapPane>
          } />
        )}
        {me && tab === "weather" && <HazardsTab me={me} projects={projects} side={roomy(panel)} />}
        {me && tab === "news" && <NewsTab projects={projects} side={roomy(panel)} />}
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
      <Speech className="absolute bottom-[calc(10.5vh+12px)] left-[calc(1vw+max(22vh,155px)+2px)] z-30" />

      <div className="absolute bottom-[4vh] right-[5vw] z-30 flex items-center gap-7" onClick={(e) => e.stopPropagation()}>
        <button onClick={() => { setStack((s) => [...s.filter((p) => p.kind !== "history"), { kind: "history" }]); setPop(null); say(reqs.length ? `Here are all ${reqs.length} of our requests.` : "No requests yet. Open an overlap to send one.", "nod"); }} aria-label="Request history"
          className="grid h-[7vh] min-h-11 w-[7vh] min-w-11 place-items-center rounded-full bg-[#ece2e6] text-grape transition hover:scale-105">
          <Clock3 className="h-[55%] w-[55%]" strokeWidth={2.5} />
        </button>
        <div className="relative">
          <button onClick={() => { setPop(pop === "bell" ? null : "bell"); if (pop !== "bell") say(unread ? `You have ${unread} new update${unread === 1 ? "" : "s"}.` : "You're all caught up!", "nod"); }} aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`} className="relative grid place-items-center text-white transition hover:scale-105">
            <Bell key={ring} className={`h-[7vh] min-h-11 w-[7vh] min-w-11 ${ring ? "wiggle" : ""}`} fill="white" strokeWidth={1.5} />
            {unread > 0 && <span className="pop-in absolute -right-1 -top-1 grid h-6 min-w-6 place-items-center rounded-full bg-[#ff1f3d] px-1 text-xs font-bold text-white">{unread}</span>}
          </button>
          {pop === "bell" && me && (
            <div className="pop-in absolute bottom-[calc(100%+14px)] right-[-60px] w-[340px] rounded-3xl border-2 border-pen bg-white p-3 shadow-xl">
              <div className="mb-1 flex items-center px-1">
                <span className="flex-1 font-logo text-lg font-semibold">Notifications</span>
                {unread > 0 && <button onClick={() => noticesApi.markRead(notes.filter((n) => !n.read_at).map((n) => n.id)).then(reload)} className="text-xs font-semibold text-grape">Mark all read</button>}
              </div>
              <div className="thin-scroll flex max-h-[46vh] flex-col gap-0.5 overflow-y-auto">
                {notes.map((n) => {
                  if (n.kind === "suggestion") {
                    return <Suggestion key={n.id} n={n} onAct={() => { setPop(null); actOn(n); }}
                      onDismiss={() => { setNotes((xs) => xs.filter((x) => x.id !== n.id)); noticesApi.dismiss(n.id); }} />;
                  }
                  const r = reqs.find((x) => x.id === n.request_id);
                  const who = r ? company(n.kind === "request" ? r.from_company : r.to_company).name : "A neighboring utility";
                  return (
                    <button key={n.id} onClick={() => { openRequest(n.request_id!); setPop(null); }} className="flex gap-2.5 rounded-2xl px-2 py-2 text-left hover:bg-soft">
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
          <button onClick={() => setPop(pop === "profile" ? null : "profile")} aria-label="Profile" className="grid h-[8vh] min-h-12 w-[8vh] min-w-12 place-items-center rounded-full border-[3px] border-white text-white transition hover:scale-105">
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
