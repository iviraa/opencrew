import { Activity, CloudLightning, Droplets, Flame, Mountain, Snowflake, Sun, Thermometer, Tornado, Wind } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { say } from "../mascot";
import { api, colorFor, company, type Jobs, type Me, type Overlap } from "../data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { PanelHeader } from "../panels";
import { SectionTitle, Split, fc, splitGeoms } from "../weather/shared";

type Period = "now7" | "weeks" | "season" | "month";
type LayerProps = { id: number; layer: string; hazard: string; product: string; label: string; rank: number; period_start: string; period_end: string; props: Record<string, unknown> };
type ClimateProps = { fips: string; days: Record<string, number>; total: number; nri: Record<string, number> };
type Layers = {
  period: Period; start?: string; end?: string; month?: number; fetched: Record<string, string>; sources: { title: string; url: string }[];
  layers: { alerts?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>; outlooks?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>;
            fires?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>; quakes?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>;
            climate?: GeoJSON.FeatureCollection<GeoJSON.Geometry, ClimateProps> };
};
type Exposure = {
  kind: "site" | "zone"; id: string; names: string[]; partners: string[]; period: string; start: string; end: string; days: number; counties: number;
  hazards: { hazard: string; label: string; why: string; affected_days: { forecast: number; low: number; high: number }; live: { id: number; layer: string; product: string; label: string; rank: number; from: string; to: string }[] }[];
  affected_days: { forecast: number; low: number; high: number }; method: string;
};
type Open = { kind: "site" | "zone"; id: string } | null;

export const HAZARD: Record<string, { label: string; color: string; icon: typeof Wind }> = {
  wind: { label: "Wind", color: "#3a86ff", icon: Wind }, storms: { label: "Storms", color: "#7c4dff", icon: CloudLightning },
  tornado: { label: "Tornado", color: "#d6336c", icon: Tornado }, winter: { label: "Winter", color: "#1098ad", icon: Snowflake },
  heat: { label: "Heat", color: "#ff7a3d", icon: Thermometer }, flood: { label: "Flood", color: "#2e9e4f", icon: Droplets },
  tropical: { label: "Tropical", color: "#c9184a", icon: Activity }, wildfire: { label: "Wildfire", color: "#e8590c", icon: Flame },
  earthquake: { label: "Earthquake", color: "#8e5cf7", icon: Mountain }, hail: { label: "Hail", color: "#00a6a6", icon: Sun },
};
const PERIODS: [Period, string][] = [["now7", "Now + 7 days"], ["weeks", "Next weeks"], ["season", "Next season"], ["month", "By month"]];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const GREY = "#c3cad9";
const day = (s: string) => new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const range = (a: number, b: number) => (a === b ? `${a}` : `${a} to ${b}`);

// one line for the beaver about what the map shows
function mapLine(l: Layers, ours: number): string {
  if (l.period === "month") return `${MONTHS[(l.month ?? 1) - 1]} history is on the map: ten years of storms by county.`;
  const n = (k: keyof Layers["layers"]) => l.layers[k]?.features.length ?? 0;
  const parts = [n("alerts") && `${n("alerts")} active alert${n("alerts") === 1 ? "" : "s"}`, n("outlooks") && `${n("outlooks")} outlook area${n("outlooks") === 1 ? "" : "s"}`,
    n("fires") && `${n("fires")} wildfire${n("fires") === 1 ? "" : "s"}`, n("quakes") && `${n("quakes")} quake${n("quakes") === 1 ? "" : "s"}`].filter(Boolean);
  if (!parts.length) return "Nothing on the hazard map for this period. Quiet for our sites.";
  return `${parts.join(", ")} on the map${ours ? `, ${ours} of our sites inside` : ""}.`;
}

export default function HazardsTab({ me, projects, side }: { me: Me; projects: Jobs | null; side: React.ReactNode | null }) {
  const [period, setPeriod] = useState<Period>("now7");
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [on, setOn] = useState<Set<string>>(new Set(Object.keys(HAZARD)));
  const [data, setData] = useState<Layers | null>(null);
  const [ov, setOv] = useState<{ overlaps: Overlap[]; jobs: Jobs } | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [exp, setExp] = useState<Exposure | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.overlaps().then(setOv).catch(() => {}); }, []);

  useEffect(() => {
    setData(null); setErr(null);
    const q = `period=${period}&month=${month}&hazards=${[...on].join(",")}`;
    api.get<Layers>(`/api/app/hazards/layers?${q}`).then((l) => { setData(l); say(mapLine(l, 0), "nod"); })
      .catch((e) => { setErr(String(e.message ?? e)); say("I couldn't load the hazard layers.", "sad"); });
  }, [period, month, on]);

  useEffect(() => {
    if (!open) { setExp(null); return; }
    setExp(null);
    api.get<Exposure>(`/api/app/hazards/exposure?kind=${open.kind}&id=${encodeURIComponent(open.id)}&period=${period}&month=${month}&hazards=${[...on].join(",")}`)
      .then((e) => {
        setExp(e);
        const top = e.hazards[0];
        const who = open.kind === "zone" ? `Overlap #${e.id}` : "This site";
        say(top ? `${who}: ${top.label.toLowerCase()} is the main exposure, ${period === "now7" ? `${top.affected_days.forecast} forecast day${top.affected_days.forecast === 1 ? "" : "s"}` : `about ${range(top.affected_days.low, top.affected_days.high)} affected days`}.` : `${who} has no hazard exposure in this period.`, top ? "surprised" : "happy");
      }).catch((e) => setErr(String(e.message ?? e)));
  }, [open, period, month, on]);

  const jobs = useMemo(() => new Map((projects?.features ?? []).map((f) => [f.properties.id, f])), [projects]);
  const partnerJobs = useMemo(() => (ov?.jobs.features ?? []).filter((f) => f.properties.org_id !== me.company), [ov, me.company]);

  const scene = useMemo<Scene>(() => {
    const areas: GeoJSON.Feature[] = [], pts: GeoJSON.Feature[] = [];
    const L = data?.layers;
    for (const f of L?.climate?.features ?? []) {
      const worst = Object.entries(f.properties.days).sort((a, b) => b[1] - a[1])[0];
      if (!worst) continue;
      areas.push({ ...f, properties: { color: HAZARD[worst[0]].color, opacity: Math.min(0.08 + f.properties.total * 0.05, 0.55),
        title: `<b>${esc(f.properties.total)} affected days a typical ${MONTHS[month - 1]}</b><br/>${Object.entries(f.properties.days).sort((a, b) => b[1] - a[1]).map(([h, d]) => `${esc(HAZARD[h].label)} ${d}`).join(" · ")}` } });
    }
    for (const key of ["outlooks", "alerts", "fires"] as const) {
      for (const f of L?.[key]?.features ?? []) {
        const p = f.properties, isPoint = f.geometry?.type === "Point";
        const props = { color: HAZARD[p.hazard]?.color ?? GREY, opacity: isPoint ? 1 : 0.14 + (p.rank ?? 1) * 0.08, radius: 4 + (p.rank ?? 1) * 1.5, stroke: "#ffffff",
          title: `<b>${esc(p.label)}</b><br/><span style="color:#5e6a8a">${esc(day(p.period_start))} to ${esc(day(p.period_end))}${p.props?.places ? `<br/>${esc(String(p.props.places).slice(0, 90))}` : ""}</span>` };
        (isPoint ? pts : areas).push({ ...f, properties: props });
      }
    }
    for (const f of L?.quakes?.features ?? []) pts.push({ ...f, properties: { color: HAZARD.earthquake.color, radius: 4 + (f.properties.rank ?? 1) * 2, stroke: "#111014", title: `<b>${esc(f.properties.label)}</b>` } });
    const sel = open?.kind === "site" ? open.id : null;
    const selZone = open?.kind === "zone" ? ov?.overlaps.find((o) => String(o.id) === open.id) : null;
    const hot = selZone ? new Set([selZone.job_a, selZone.job_b]) : null;
    const draw = (f: GeoJSON.Feature<GeoJSON.Geometry, Jobs["features"][number]["properties"]>, mine: boolean) => {
      const id = f.properties.id, active = sel === id || hot?.has(id);
      const dim = (sel || hot) && !active;
      return { ...f, properties: { color: mine ? me.color : colorFor(f.properties.org_id), width: active ? 5 : mine ? 3 : 2, radius: active ? 7 : mine ? 5 : 3.5,
        opacity: dim ? 0.2 : mine ? 0.95 : 0.6, stroke: "#ffffff", pick: `site:${id}`,
        title: `<b>${esc(f.properties.name)}</b><br/>${esc(company(f.properties.org_id)?.name ?? f.properties.org_id)}` } } as GeoJSON.Feature;
    };
    const g = splitGeoms([...partnerJobs.map((f) => draw(f, false)), ...(projects?.features ?? []).map((f) => draw(f, true))]);
    for (const o of ov?.overlaps ?? []) {
      const c = o.link.coordinates, a = c[0], b = c[c.length - 1];
      const active = selZone?.id === o.id;
      pts.push({ type: "Feature", geometry: { type: "Point", coordinates: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] },
        properties: { color: "#111014", radius: active ? 8 : 5, stroke: "#ffffff", opacity: sel || (hot && !active) ? 0.3 : 0.9, pick: `zone:${o.id}`,
          title: `<b>Overlap #${o.id}</b><br/>${esc(o.a_name)}<br/><span style="color:#5e6a8a">with ${esc(o.b_name)}</span>` } });
    }
    return { areas: fc(areas), lines: fc(g.lines), points: fc([...pts, ...g.points]) };
  }, [data, projects, partnerJobs, ov, open, me, month]);

  const flyTo = (b: [number, number, number, number] | null, key: string, maxZoom = 9) => b && setFit({ bbox: b, key: key + Date.now(), maxZoom });
  const pick = (p: string) => {
    const [kind, id] = p.split(":") as ["site" | "zone", string];
    setOpen({ kind, id });
    if (kind === "site") { const f = jobs.get(id) ?? partnerJobs.find((x) => x.properties.id === id); if (f) flyTo(bboxOf([fc([f])]), id); }
    else { const o = ov?.overlaps.find((x) => String(x.id) === id); if (o) flyTo(bboxOf([fc([{ type: "Feature", geometry: o.link, properties: {} }])]), id, 10); }
  };
  const toggle = (h: string) => setOn((s) => { const n = new Set(s); if (n.has(h)) n.delete(h); else n.add(h); return n; });

  const items = useMemo(() => {
    const L = data?.layers;
    const all = [...(L?.alerts?.features ?? []), ...(L?.outlooks?.features ?? []), ...(L?.fires?.features ?? []), ...(L?.quakes?.features ?? [])];
    return all.sort((a, b) => (b.properties.rank ?? 0) - (a.properties.rank ?? 0) || a.properties.period_start.localeCompare(b.properties.period_start));
  }, [data]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of items) c[f.properties.hazard] = (c[f.properties.hazard] ?? 0) + 1;
    for (const f of data?.layers.climate?.features ?? []) for (const h of Object.keys(f.properties.days)) c[h] = (c[h] ?? 0) + 1;
    return c;
  }, [items, data]);

  const legend = (
    <div className="absolute right-3 top-3 flex max-w-[60%] flex-wrap items-center justify-end gap-1.5 rounded-2xl border-2 border-pen bg-white/95 px-2.5 py-1.5 text-[11px] font-semibold">
      {Object.entries(HAZARD).filter(([h]) => on.has(h) && counts[h]).map(([h, v]) => (
        <span key={h} className="flex items-center gap-1"><span className="h-2.5 w-2.5 rounded-full" style={{ background: v.color }} />{v.label}</span>
      ))}
      {!Object.keys(counts).some((h) => on.has(h)) && <span className="text-muted">No hazards in view</span>}
    </div>
  );

  const controls = (
    <>
      <div className="mb-2 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
        {PERIODS.map(([k, label]) => (
          <button key={k} onClick={() => { setPeriod(k); setOpen(null); }} className={`flex-1 rounded-full py-1 ${period === k ? "bg-white shadow-sm" : "text-muted"}`}>{label}</button>
        ))}
      </div>
      {period === "month" && (
        <div className="mb-2 grid grid-cols-12 gap-0.5" role="tablist" aria-label="Month">
          {MONTHS.map((m, i) => (
            <button key={m} role="tab" aria-selected={month === i + 1} onClick={() => setMonth(i + 1)}
              className={`rounded-lg py-1 text-[10px] font-semibold ${month === i + 1 ? "bg-ink text-white" : "text-muted hover:bg-soft"}`}>{m}</button>
          ))}
        </div>
      )}
      <div className="mb-2 flex flex-wrap gap-1">
        {Object.entries(HAZARD).map(([h, v]) => (
          <button key={h} onClick={() => toggle(h)} aria-pressed={on.has(h)}
            className={`flex items-center gap-1 rounded-full border-2 px-2 py-0.5 text-[11px] font-semibold ${on.has(h) ? "border-transparent text-white" : "border-line bg-white text-muted"}`}
            style={on.has(h) ? { background: v.color } : undefined}>
            <v.icon size={11} />{v.label}{counts[h] ? ` ${counts[h]}` : ""}
          </button>
        ))}
      </div>
    </>
  );

  const list = (
    <>
      <PanelHeader title="Hazards" sub={data?.start ? `${day(data.start)} to ${day(data.end!)}` : period === "month" ? `A typical ${MONTHS[month - 1]}, from ten years of storms` : "Loading"} />
      {controls}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-1 overflow-y-auto pr-2">
        {!data && !err && <p className="text-sm text-muted"><span className="dots">Loading hazard layers</span></p>}
        {err && <p className="text-sm text-warn">{err}</p>}
        {data && period !== "month" && !items.length && (
          <div className="rounded-2xl bg-save-soft/70 px-3 py-3 text-sm"><div className="font-semibold text-save">Nothing active</div>
            <p className="mt-1 text-muted">No alert, outlook, wildfire or earthquake for the picked hazards in this period.</p></div>
        )}
        {period === "month" && data && (
          <p className="rounded-2xl bg-soft px-3 py-2 text-sm text-muted">Counties shaded by affected days in a typical {MONTHS[month - 1]}. Click a project or overlap for its exposure.</p>
        )}
        {items.length > 0 && <SectionTitle>On the map · {items.length}</SectionTitle>}
        {items.slice(0, 80).map((f) => {
          const p = f.properties, H = HAZARD[p.hazard];
          return (
            <button key={p.id} onClick={() => { const b = bboxOf([fc([f])]); if (b) flyTo(b, String(p.id), 8); }} className="flex gap-2.5 rounded-2xl px-2 py-1.5 text-left hover:bg-soft">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-white" style={{ background: H?.color ?? GREY }}><H.icon size={14} /></span>
              <span className="min-w-0">
                <span className="line-clamp-2 block text-sm font-semibold leading-snug">{p.label}</span>
                <span className="block text-xs text-muted">{day(p.period_start)} to {day(p.period_end)}{p.props?.places ? ` · ${String(p.props.places).slice(0, 60)}` : ""}</span>
              </span>
            </button>
          );
        })}
        {data && (
          <p className="mt-2 px-2 text-[11px] text-faint">Sources: {data.sources.map((s) => s.title).join("; ")}.</p>
        )}
      </div>
    </>
  );

  const detail = open && (
    <>
      <PanelHeader title={open.kind === "zone" ? `Overlap #${open.id}` : exp?.names[0] ?? "Site"} onBack={() => setOpen(null)}
        sub={exp ? `${day(exp.start)} to ${day(exp.end)} · ${exp.days} days${exp.partners.length > 1 ? ` · with ${exp.partners.filter((p) => p !== me.company).map((p) => company(p)?.short ?? p).join(", ")}` : ""}` : "Assessing"} />
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto pr-2">
        {!exp && !err && <p className="text-sm text-muted"><span className="dots">Checking exposure</span></p>}
        {exp && open.kind === "zone" && <p className="text-xs text-muted">{exp.names[0]} with {exp.names[1]}</p>}
        {exp && (
          <div className="rounded-2xl bg-soft px-3 py-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Affected days in this period</div>
            <div className="font-logo text-2xl font-semibold">{period === "now7" ? exp.affected_days.forecast : range(exp.affected_days.low, exp.affected_days.high)}</div>
            <div className="text-xs text-muted">{period === "now7" ? "days with an active alert or outlook over the works" : `typical days with a work-affecting event, across ${exp.counties} count${exp.counties === 1 ? "y" : "ies"} under the works`}</div>
          </div>
        )}
        {exp?.hazards.map((h) => {
          const H = HAZARD[h.hazard];
          return (
            <div key={h.hazard} className="rounded-2xl border-2 border-line px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="grid h-6 w-6 place-items-center rounded-full text-white" style={{ background: H.color }}><H.icon size={13} /></span>
                <span className="text-sm font-semibold">{h.label}</span>
                <span className="flex-1" />
                <span className="text-sm font-semibold">{period === "now7" ? `${h.affected_days.forecast} d` : `${range(h.affected_days.low, h.affected_days.high)} d`}</span>
              </div>
              <div className="mt-0.5 text-xs text-muted">{h.why}</div>
              {h.live.map((x) => <div key={x.id} className="mt-1 rounded-xl bg-soft px-2 py-1 text-xs">{x.label} · {day(x.from)} to {day(x.to)}</div>)}
            </div>
          );
        })}
        {exp && !exp.hazards.length && <p className="rounded-2xl bg-save-soft/70 px-3 py-2 text-sm text-save">No work-affecting hazard touches this in the period.</p>}
        {exp && <p className="px-1 text-[11px] text-faint">{exp.method}</p>}
      </div>
    </>
  );

  return <Split map={<MapPane scene={scene} fit={fit} onPick={pick}>{legend}</MapPane>} side={side ?? (open ? detail : list)} />;
}
