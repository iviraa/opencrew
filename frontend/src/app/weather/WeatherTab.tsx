import { AlertTriangle, CloudLightning, Droplets, HardHat, ShieldCheck, Tornado, Wind, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { say, type Mood } from "../mascot";
import type { HeadsUp } from "../../api-outlook";
import { RISK_COLOR, riskColor } from "../../api-outlook";
import { ago, month, publicApi, type Jobs } from "../data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { PanelHeader } from "../panels";
import { ScenarioSwitch, SectionTitle, Split, fc, splitGeoms, when, type Scenario } from "./shared";

type AtRisk = { id: string; name: string; building: boolean };
type AreaProps = { id: number; product: string; level: string; rank: number; label: string; kind: string; valid_from: string; valid_to: string; projects: AtRisk[] };
type Day = { date: string; view: string; label: string; max_rank: number; at_risk: number; areas: GeoJSON.FeatureCollection<GeoJSON.Geometry, AreaProps> };
type AlertProps = { id: number; label: string; headline: string; severity: string; places: string; expire: string; projects: string[] };
type Weather = { scenario: string; known: string; days: Day[]; alerts: GeoJSON.FeatureCollection<GeoJSON.Geometry, AlertProps>; heads_up: HeadsUp[] };
type Open = { kind: "project"; id: string } | { kind: "heads"; id: string } | { kind: "alert"; id: number } | null;

const KIND_ICON: Record<string, typeof Wind> = { "Severe storms": CloudLightning, "Flash flooding": Droplets, "Tropical storm winds": Wind };
const HEADS_ICON: Record<string, typeof Wind> = { severe: CloudLightning, severe48: CloudLightning, flood: Droplets, tropical: Tornado, wind: Wind, watch: Zap };
const GREY = "#c3cad9";

// worst outlook area each of our projects sits in on one day
function worstByProject(day: Day | undefined) {
  const out = new Map<string, { rank: number; areas: AreaProps[]; building: boolean }>();
  for (const f of day?.areas.features ?? []) {
    for (const p of f.properties.projects) {
      const cur = out.get(p.id) ?? { rank: 0, areas: [], building: p.building };
      cur.rank = Math.max(cur.rank, f.properties.rank ?? 0);
      const same = cur.areas.findIndex((x) => x.kind === f.properties.kind);  // nested wind bands: keep the worst per hazard
      if (same < 0) cur.areas.push(f.properties);
      else if ((f.properties.rank ?? 0) > (cur.areas[same].rank ?? 0)) cur.areas[same] = f.properties;
      out.set(p.id, cur);
    }
  }
  return out;
}

const dayNum = (d: string) => Number(d.slice(8, 10));

// one short line for the beaver about the week ahead
function forecastLine(w: Weather, replay: boolean): [string, Mood] {
  const lead = replay ? "Helene week: " : "";
  const s = (n: number) => (n === 1 ? "" : "s");
  const today = w.days[0]?.at_risk ?? 0;
  const next = w.days.find((d) => d.at_risk > 0);
  if (today) return [`${lead}heads up, ${today} of our project${s(today)} ${today === 1 ? "is" : "are"} in a risk area today.`, "surprised"];
  if (next) return [`${lead}calm today. Watch ${next.label}: ${next.at_risk} project${s(next.at_risk)} at risk.`, "nod"];
  return [replay ? "Helene week: none of our sites are in a risk area." : "The weather looks good for our sites this week!", "happy"];
}

export default function WeatherTab({ projects, side }: { projects: Jobs | null; side: React.ReactNode | null }) {
  const [scenario, setScenario] = useState<Scenario>("now");
  const [data, setData] = useState<Weather | null>(null);
  const [dayIdx, setDayIdx] = useState(0);
  const [open, setOpen] = useState<Open>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const org = projects?.features[0]?.properties.org_id;

  useEffect(() => {
    if (!projects) return;
    setData(null); setErr(null); setOpen(null);
    say(scenario === "now" ? "Checking the forecast..." : "Loading the Helene week...", "thinking");
    const q = `scenario=${scenario === "now" ? "none" : "helene"}${org ? `&org=${org}` : ""}`;
    publicApi.get<Weather>(`/api/app/weather?${q}`).then((w) => {
      setData(w);
      say(...forecastLine(w, scenario === "helene"));
      const first = w.days.findIndex((d) => d.max_rank > 0);  // open on the first day with something to see
      setDayIdx(first > 0 && !w.days[0].areas.features.length ? first : 0);
    }).catch((e) => { setErr(String(e)); say("I couldn't get the forecast.", "sad"); });
  }, [scenario, org, projects]);

  const day = data?.days[dayIdx];
  const risk = useMemo(() => worstByProject(day), [day]);
  const jobs = useMemo(() => new Map((projects?.features ?? []).map((f) => [f.properties.id, f])), [projects]);
  const atRisk = useMemo(() => [...risk.entries()].map(([id, r]) => ({ id, ...r, name: jobs.get(id)?.properties.name ?? id }))
    .sort((a, b) => b.rank - a.rank || Number(b.building) - Number(a.building) || a.name.localeCompare(b.name)), [risk, jobs]);
  const alerts = useMemo(() => data?.alerts.features ?? [], [data]);
  const heads = data?.heads_up ?? [];
  const replay = scenario === "helene";
  const selectedJob = open?.kind === "project" ? open.id : null;

  const scene = useMemo<Scene>(() => {
    const areas: GeoJSON.Feature[] = (day?.areas.features ?? []).map((f) => ({ ...f, properties: {
      color: riskColor(f.properties.rank), opacity: 0.1 + (f.properties.rank ?? 1) * 0.04,
      title: `<b>${esc(f.properties.kind)}</b><br/>${esc(f.properties.label)}<br/><span style="color:#5e6a8a">${f.properties.projects.length} of our projects inside</span>` } }));
    alerts.forEach((f) => areas.push({ ...f, properties: { color: "#c9184a", opacity: 0.28, pick: `alert:${f.properties.id}`,
      title: `<b>${esc(f.properties.label)}</b><br/>${esc(f.properties.places)}` } }));
    const ours = (projects?.features ?? []).map((f) => {
      const r = risk.get(f.properties.id);
      const on = !selectedJob || selectedJob === f.properties.id;
      return { ...f, properties: {
        color: r ? riskColor(r.rank) : GREY, width: selectedJob === f.properties.id ? 6 : r ? 3.5 : 2, radius: r ? 6 : 3.5,
        opacity: on ? (r ? 1 : 0.7) : 0.25, stroke: r ? "#111014" : "#ffffff", pick: `job:${f.properties.id}`,
        title: `<b>${esc(f.properties.name)}</b>${r ? `<br/>${esc(r.areas.map((a) => a.kind).filter((k, i, xs) => xs.indexOf(k) === i).join(", "))}` : ""}`,
      } } as GeoJSON.Feature;
    });
    const g = splitGeoms(ours);
    return { areas: fc(areas), lines: fc(g.lines), points: fc(g.points) };
  }, [day, alerts, projects, risk, selectedJob]);

  const flyTo = (b: [number, number, number, number] | null, key: string, maxZoom = 9) => b && setFit({ bbox: b, key: key + Date.now(), maxZoom });
  const openProject = (id: string) => {
    setOpen({ kind: "project", id });
    const f = jobs.get(id);
    if (f) flyTo(bboxOf([fc([f])]), id);
  };
  const onPick = (p: string) => {
    if (p.startsWith("job:")) openProject(p.slice(4));
    else if (p.startsWith("alert:")) setOpen({ kind: "alert", id: Number(p.slice(6)) });
  };

  const legend = (
    <div className="absolute right-3 top-3 flex items-center gap-2 rounded-full border-2 border-pen bg-white/95 px-3 py-1 text-[11px] font-semibold">
      <span className="text-muted">Risk</span>
      <span className="text-faint">low</span>
      {RISK_COLOR.map((c) => <span key={c} className="h-2.5 w-4 rounded-full" style={{ background: c }} />)}
      <span className="text-faint">high</span>
    </div>
  );

  const list = (
    <>
      <PanelHeader title="Weather outlook" sub={replay ? "As of Sept 25, 2024, two days before Helene" : "Official forecasts for the next 7 days"} />
      <ScenarioSwitch value={scenario} onChange={setScenario} />
      {data && (
        <div className="mb-3 grid grid-cols-7 gap-1" role="tablist" aria-label="Forecast day">
          {data.days.map((d, i) => (
            <button key={d.date} role="tab" aria-selected={i === dayIdx} onClick={() => { setDayIdx(i); setOpen(null); }}
              className={`flex flex-col items-center rounded-xl py-1 text-[11px] font-semibold ${i === dayIdx ? "bg-ink text-white" : "text-muted hover:bg-soft"}`}>
              <span>{i === 0 ? "Today" : d.label}</span>
              <span className="font-logo text-sm">{dayNum(d.date)}</span>
              <span className="mt-0.5 h-1.5 w-1.5 rounded-full" style={{ background: d.max_rank ? riskColor(d.max_rank) : "transparent" }} />
            </button>
          ))}
        </div>
      )}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1 overflow-y-auto pr-2">
        {!data && !err && <p className="text-sm text-muted"><span className="dots">Checking forecasts</span></p>}
        {err && <p className="text-sm text-warn">{err}</p>}
        {day && (atRisk.length ? (
          <div className="mb-1 rounded-2xl px-3 py-2.5" style={{ background: `${riskColor(day.max_rank)}22` }}>
            <div className="font-logo text-lg font-semibold leading-tight">{atRisk.length} of your projects in a risk area</div>
            <div className="text-xs text-muted">{atRisk.filter((p) => p.building).length} of them are under construction {dayIdx === 0 ? "today" : `on ${day.label}`}</div>
          </div>
        ) : (
          <div className="mb-1 rounded-2xl bg-save-soft/70 px-3 py-2.5 text-sm">
            <div className="flex items-center gap-1.5 font-semibold text-save"><ShieldCheck size={16} /> All clear {dayIdx === 0 ? "today" : `on ${day.label}`}</div>
            <p className="mt-0.5 text-xs text-muted">
              {day.areas.features.length ? "There are forecast risk areas, but none touch your projects." : "No severe storm, flash flood or tropical wind outlook for this day."}
              {!replay && dayIdx === 0 && data?.days.some((d) => d.max_rank) && " Tap the days with a dot to see what is coming."}
            </p>
            {!replay && !data?.days.some((d) => d.max_rank) && <button onClick={() => setScenario("helene")} className="mt-1.5 text-xs font-semibold text-grape underline">See what a storm week looks like</button>}
          </div>
        ))}

        {atRisk.length > 0 && <SectionTitle><HardHat size={13} /> Your projects at risk</SectionTitle>}
        {atRisk.slice(0, 60).map((p) => (
          <button key={p.id} onClick={() => openProject(p.id)} className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
            <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: riskColor(p.rank) }} />
            <span className="min-w-0">
              <span className="line-clamp-2 block text-sm font-semibold leading-snug">{p.name}</span>
              <span className="block text-xs text-muted">
                {p.areas.map((a) => `${a.kind} ${a.level}`).join(", ")}{p.building ? " · building now" : ""}
              </span>
            </span>
          </button>
        ))}
        {atRisk.length > 60 && <p className="px-2 text-xs text-muted">and {atRisk.length - 60} more on the map</p>}

        {alerts.length > 0 && <SectionTitle><AlertTriangle size={13} /> Active alerts</SectionTitle>}
        {alerts.map((a) => (
          <button key={a.properties.id} onClick={() => { setOpen({ kind: "alert", id: a.properties.id }); flyTo(bboxOf([fc([a])]), `a${a.properties.id}`, 8); }}
            className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
            <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-[#c9184a]" />
            <span className="min-w-0">
              <span className="block text-sm font-semibold leading-snug">{a.properties.label}</span>
              <span className="line-clamp-1 block text-xs text-muted">{a.properties.places}</span>
            </span>
          </button>
        ))}

        {heads.length > 0 && <SectionTitle><CloudLightning size={13} /> This week's heads-up</SectionTitle>}
        {heads.map((h) => {
          const Icon = HEADS_ICON[h.kind] ?? CloudLightning;
          return (
            <button key={h.id} onClick={() => { setOpen({ kind: "heads", id: h.id }); flyTo(h.bbox, h.id, 8); }} className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-white" style={{ background: riskColor(h.rank) }}><Icon size={14} /></span>
              <span className="min-w-0">
                <span className="text-xs font-semibold text-muted">{h.day} · {h.level}</span>
                <span className="line-clamp-2 block text-sm leading-snug">{h.text}</span>
              </span>
            </button>
          );
        })}
      </div>
    </>
  );

  let detail: React.ReactNode = null;
  if (open?.kind === "project" && data) {
    const f = jobs.get(open.id);
    const r = risk.get(open.id);
    const week = data.days.map((d) => worstByProject(d).get(open.id)?.rank ?? 0);
    detail = (
      <>
        <PanelHeader title={f?.properties.name ?? "Project"} onBack={() => setOpen(null)}
          sub={f ? `${month(f.properties.start_at)} to ${month(f.properties.end_at)}${f.properties.voltage_kv ? ` · ${f.properties.voltage_kv} kV` : ""}` : undefined} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
          <div>
            <h3 className="mb-1.5 text-sm font-semibold text-muted">This week</h3>
            <div className="grid grid-cols-7 gap-1">
              {data.days.map((d, i) => (
                <button key={d.date} onClick={() => setDayIdx(i)} className={`flex flex-col items-center rounded-xl py-1 text-[11px] font-semibold ${i === dayIdx ? "ring-2 ring-ink" : ""}`}>
                  <span className="text-muted">{i === 0 ? "Today" : d.label}</span>
                  <span className="mt-1 h-3 w-3 rounded-full" style={{ background: week[i] ? riskColor(week[i]) : "#e6eaf2" }} />
                </button>
              ))}
            </div>
          </div>
          {r ? (
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-muted">{dayIdx === 0 ? "Today" : day?.label}: in {r.areas.length === 1 ? "one risk area" : `${r.areas.length} risk areas`}</h3>
              {[...r.areas].sort((a, b) => b.rank - a.rank).map((a) => {
                const Icon = KIND_ICON[a.kind] ?? CloudLightning;
                return (
                  <div key={`${a.id}-${a.valid_from}`} className="flex gap-2.5 rounded-xl border-2 border-line px-2.5 py-2">
                    <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-white" style={{ background: riskColor(a.rank) }}><Icon size={14} /></span>
                    <span className="min-w-0 text-sm">
                      <span className="block font-semibold">{a.kind} · {a.level}</span>
                      <span className="block text-xs text-muted">{a.label}</span>
                    </span>
                  </div>
                );
              })}
              <p className="rounded-xl bg-soft px-2.5 py-2 text-xs text-muted">
                {r.building ? "Work is scheduled on this project now. Check crane and line work plans for this day." : "No construction is scheduled on this project that day, so the risk is to the site, not crews."}
              </p>
            </div>
          ) : (
            <p className="flex items-center gap-1.5 rounded-xl bg-save-soft/70 px-2.5 py-2 text-sm text-save"><ShieldCheck size={15} /> No forecast risk here {dayIdx === 0 ? "today" : `on ${day?.label}`}.</p>
          )}
        </div>
      </>
    );
  } else if (open?.kind === "heads") {
    const h = heads.find((x) => x.id === open.id);
    detail = h && (
      <>
        <PanelHeader title={`${h.day} · ${h.level}`} sub={h.issued ? `Issued ${when(h.issued, replay, ago)}` : undefined} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
          <p className="rounded-2xl rounded-tl-sm px-3 py-2 text-sm" style={{ background: `${riskColor(h.rank)}22` }}>{h.text}</p>
          {h.sites.length > 0 && (
            <div>
              <h3 className="mb-1 text-sm font-semibold text-muted">Active work sites inside</h3>
              <ul className="flex flex-col gap-1 text-sm">{h.sites.map((s) => <li key={s} className="rounded-xl bg-soft px-2.5 py-1.5">{s}</li>)}</ul>
            </div>
          )}
        </div>
      </>
    );
  } else if (open?.kind === "alert") {
    const a = alerts.find((x) => x.properties.id === open.id)?.properties;
    detail = a && (
      <>
        <PanelHeader title={a.label} sub={a.expire ? `Until ${new Date(a.expire).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}` : undefined} onBack={() => setOpen(null)} />
        <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
          {a.severity && <span className="self-start rounded-full bg-gpc-soft px-2 py-0.5 text-xs font-semibold text-[#c23b3b]">{a.severity}</span>}
          <p className="text-sm">{a.headline}</p>
          <p className="text-xs text-muted">{a.places}</p>
          <div>
            <h3 className="mb-1 text-sm font-semibold text-muted">Your projects inside</h3>
            {a.projects.length ? <ul className="flex flex-col gap-1 text-sm">{a.projects.map((p) => <li key={p} className="rounded-xl bg-soft px-2.5 py-1.5">{p}</li>)}</ul>
              : <p className="text-sm text-muted">None of your projects are inside this alert.</p>}
          </div>
        </div>
      </>
    );
  }

  return <Split map={<MapPane scene={scene} fit={fit} onPick={onPick}>{data && legend}</MapPane>} side={side ?? detail ?? list} />;
}
