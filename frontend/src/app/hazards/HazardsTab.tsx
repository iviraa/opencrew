import { Activity, CloudLightning, Droplets, Flame, Mountain, Snowflake, Sun, Thermometer, Tornado, Wind } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { say } from "../mascot";
import { api, colorFor, company, publicApi, usd, type Jobs, type Me, type Overlap } from "../data";
import MapPane, { bboxOf, esc, type Fit, type Scene } from "../MapPane";
import { Chip, Disc, ListRow, PanelHeader } from "../panels";
import { SectionTitle, Split, fc, splitGeoms } from "../weather/shared";
import type { HazardControl } from "../maptools/types";

type Period = "now7" | "weeks" | "season" | "month";
type LayerProps = { id: number; layer: string; hazard: string; product: string; label: string; rank: number; period_start: string; period_end: string; props: Record<string, unknown> };
type ClimateProps = { fips: string; days: Record<string, number>; total: number; nri: Record<string, number> };
type Layers = {
  period: Period; start?: string; end?: string; month?: number; fetched: Record<string, string>; sources: { title: string; url: string }[];
  layers: { alerts?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>; outlooks?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>;
            fires?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>; quakes?: GeoJSON.FeatureCollection<GeoJSON.Geometry, LayerProps>;
            climate?: GeoJSON.FeatureCollection<GeoJSON.Geometry, ClimateProps> };
};
type Range = { low: number; high: number };
type CostItem = { hazard: string; label: string; days: Range; option: { low: string; high: string }; per_day: Range; premium: Range; total: Range; rules: string[] };
type SiteCost = { kind: "site"; id: string; name: string; inside_window: boolean; per_day: Record<"low" | "high", { crew: number; equipment: number; standby: number }>; items: CostItem[]; total: Range; assumptions: string[]; method: string };
type ZoneCost = { kind: "zone"; id: number; sites: SiteCost[]; total: Range; assumptions: string[]; method: string };
type Coordination = {
  partners: string[]; separate: Range; coordinated: Range; savings: Range; items: { name: string; low: number; high: number; shared_days: Range }[];
  one_off: { name: string; low: number; high: number }[]; best_months: { month: number; label: string; cost_per_30d: Range; days: Range; saves_vs_period: Range }[];
};
type Sourced = { low: number; high: number; unit: string; label: string; source: string; url?: string | null; page?: string; verified: boolean; note?: string };
export type HazardFocus = { kind: "site" | "zone"; id: string; period?: Period; month?: number; at: number };
type Exposure = {
  kind: "site" | "zone"; id: string; cost?: SiteCost | ZoneCost; coordination?: Coordination; names: string[]; partners: string[]; period: string; start: string; end: string; days: number; counties: number;
  hazards: { hazard: string; label: string; why: string; affected_days: { forecast: number; low: number; high: number }; leans: string[]; live: { id: number; layer: string; product: string; label: string; rank: number; from: string; to: string }[] }[];
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
const day = (s: string) => new Date(s.length === 10 ? `${s}T12:00:00` : s).toLocaleDateString("en-US", { month: "short", day: "numeric" });  // date-only strings stay on their day
const PAD = 1.5;  // degrees around our sites that count as "near"
const range = (a: number, b: number) => (a === b ? `${a}` : `${a} to ${b}`);
const money = (r: Range) => (r.low === r.high ? usd(r.low) : `${usd(r.low)} to ${usd(r.high)}`);
const when = (p: Period, m: number) => (p === "now7" ? "this week" : p === "weeks" ? "over the next weeks" : p === "season" ? "next season" : `in a typical ${MONTHS[m - 1]}`);

// one line for the beaver about what the map shows
function mapLine(l: Layers): string {
  if (l.period === "month") return `${MONTHS[(l.month ?? 1) - 1]} history is on the map: ten years of storms by county.`;
  const n = (k: keyof Layers["layers"]) => l.layers[k]?.features.length ?? 0;
  const parts = [n("alerts") && `${n("alerts")} active alert${n("alerts") === 1 ? "" : "s"}`, n("outlooks") && `${n("outlooks")} outlook area${n("outlooks") === 1 ? "" : "s"}`,
    n("fires") && `${n("fires")} wildfire${n("fires") === 1 ? "" : "s"}`, n("quakes") && `${n("quakes")} quake${n("quakes") === 1 ? "" : "s"}`].filter(Boolean);
  if (!parts.length) return "Nothing on the hazard map for this period. Quiet for our sites.";
  return `${parts.join(", ")} on the map nationwide.`;
}

export default function HazardsTab({ me, projects, side, focus, control }: { me: Me; projects: Jobs | null; side: React.ReactNode | null; focus?: HazardFocus | null; control?: HazardControl | null }) {
  const [period, setPeriod] = useState<Period>(focus?.period ?? "now7");
  const [month, setMonth] = useState(focus?.month ?? new Date().getMonth() + 1);
  const [sourced, setSourced] = useState<Record<string, Sourced>>({});
  const [showSources, setShowSources] = useState(false);
  const [on, setOn] = useState<Set<string>>(new Set(Object.keys(HAZARD)));
  const [data, setData] = useState<Layers | null>(null);
  const [ov, setOv] = useState<{ overlaps: Overlap[]; jobs: Jobs } | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [exp, setExp] = useState<Exposure | null>(null);
  const [fit, setFit] = useState<Fit | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.overlaps().then(setOv).catch(() => {}); publicApi.get<Record<string, Sourced>>("/api/assumptions").then(setSourced).catch(() => {}); }, []);
  useEffect(() => {  // another tab asked to assess one site or overlap here
    if (!focus) return;
    if (focus.period) setPeriod(focus.period);
    if (focus.month) setMonth(focus.month);
    setOpen({ kind: focus.kind, id: focus.id });
  }, [focus?.at]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // crewly set the period, month or hazards from the chat
    if (!control) return;
    if (control.period) setPeriod(control.period);
    if (control.month) setMonth(control.month);
    if (control.hazards?.length) setOn(new Set(control.hazards));
  }, [control?.at]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setData(null); setErr(null);
    const q = `period=${period}&month=${month}&hazards=${[...on].join(",")}`;
    api.get<Layers>(`/api/app/hazards/layers?${q}`).then((l) => { setData(l); say(mapLine(l), "nod"); })
      .catch((e) => { setErr(String(e.message ?? e)); say("I couldn't load the hazard layers.", "sad"); });
  }, [period, month, on]);

  useEffect(() => {
    if (!open) { setExp(null); return; }
    setExp(null);
    api.get<Exposure>(`/api/app/hazards/exposure?kind=${open.kind}&id=${encodeURIComponent(open.id)}&period=${period}&month=${month}&hazards=${[...on].join(",")}&cost=1`)
      .then((e) => {
        setExp(e);
        const top = e.hazards[0];
        const who = open.kind === "zone" ? `Overlap #${e.id}` : "This site";
        const active = period === "now7" && !e.affected_days.forecast;
        const partner = e.partners.find((p) => p !== me.company);
        if (e.cost && e.cost.total.high > 0) {
          say(e.coordination && e.coordination.savings.high > 0
            ? `${who} ${when(period, month)} adds about ${money(e.cost.total)}; coordinating with ${company(partner ?? "")?.short ?? "the neighbor"} saves ${money(e.coordination.savings)}.`
            : `${who} ${when(period, month)} adds about ${money(e.cost.total)} of weather cost.`, "talking");
          return;
        }
        say(!top ? `${who} has no hazard exposure in this period.`
          : active ? `${who}: nothing active over the works this week. A typical week here sees ${range(e.affected_days.low, e.affected_days.high)} affected days.`
          : `${who}: ${top.label.toLowerCase()} is the main exposure, ${period === "now7" ? `${top.affected_days.forecast} forecast day${top.affected_days.forecast === 1 ? "" : "s"}` : `about ${range(top.affected_days.low, top.affected_days.high)} affected days`}.`,
          !top || active ? "happy" : "surprised");
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

  const home = useMemo(() => bboxOf([projects ?? undefined]), [projects]);
  const near = (f: GeoJSON.Feature) => {
    const b = bboxOf([fc([f])]);
    return !!home && !!b && b[2] >= home[0] - PAD && b[0] <= home[2] + PAD && b[3] >= home[1] - PAD && b[1] <= home[3] + PAD;
  };
  const items = useMemo(() => {
    const L = data?.layers;
    const all = [...(L?.alerts?.features ?? []), ...(L?.outlooks?.features ?? []), ...(L?.fires?.features ?? []), ...(L?.quakes?.features ?? [])];
    return all.sort((a, b) => Number(near(b)) - Number(near(a)) || (b.properties.rank ?? 0) - (a.properties.rank ?? 0) || a.properties.period_start.localeCompare(b.properties.period_start));
  }, [data, home]);  // eslint-disable-line react-hooks/exhaustive-deps
  const nearCount = useMemo(() => items.filter(near).length, [items, home]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (home && !fit) setFit({ bbox: home, key: "home", maxZoom: 8 }); }, [home]);  // eslint-disable-line react-hooks/exhaustive-deps
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

  const periodRow = (
    <>
      <div className="mb-2 flex gap-1 rounded-full bg-soft p-1 text-xs font-semibold">
        {PERIODS.map(([k, label]) => (
          <button key={k} onClick={() => setPeriod(k)} className={`flex-1 rounded-full py-1 ${period === k ? "bg-white shadow-sm" : "text-muted"}`}>{label}</button>
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
    </>
  );

  const controls = (
    <>
      {periodRow}
      <select aria-label="Assess a site or overlap" value={open ? `${open.kind}:${open.id}` : ""} onChange={(e) => e.target.value && pick(e.target.value)}
        className="mb-2 w-full rounded-full border-2 border-line bg-white px-3 py-1.5 text-sm outline-none focus:border-pen">
        <option value="">Assess a site or overlap...</option>
        <optgroup label="Our overlaps">
          {(ov?.overlaps ?? []).map((o) => <option key={o.id} value={`zone:${o.id}`}>#{o.id} {o.a_org === me.company ? o.a_name : o.b_name} with {company(o.a_org === me.company ? o.b_org : o.a_org)?.short ?? "neighbor"}</option>)}
        </optgroup>
        <optgroup label="Our sites">
          {(projects?.features ?? []).map((f) => <option key={f.properties.id} value={`site:${f.properties.id}`}>{f.properties.name}</option>)}
        </optgroup>
      </select>
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
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2 overflow-y-auto px-0.5 pb-1 pr-2">
        {!data && !err && <p className="text-sm text-muted"><span className="dots">Loading hazard layers</span></p>}
        {err && <p className="text-sm text-warn">{err}</p>}
        {data && period !== "month" && !items.length && (
          <div className="rounded-2xl border-2 border-save/30 bg-save-soft/60 px-3 py-3 text-sm"><div className="font-semibold text-save">Nothing active</div>
            <p className="mt-1 text-xs text-muted">No alert, outlook, wildfire or earthquake for the picked hazards in this period.</p></div>
        )}
        {period === "month" && data && (
          <p className="card-still px-3 py-2 text-xs leading-snug text-muted">Counties are shaded by affected days in a typical {MONTHS[month - 1]}. Pick a project or overlap for its exposure.</p>
        )}
        {items.length > 0 && <SectionTitle>Near our sites · {nearCount}</SectionTitle>}
        {items.length > 0 && !nearCount && <p className="px-2 text-sm text-muted">Nothing active near our sites.</p>}
        {items.slice(0, 80).map((f, i) => {
          const p = f.properties, H = HAZARD[p.hazard];
          return (
            <div key={p.id} className="contents">
            {i === nearCount && <SectionTitle>Elsewhere · {items.length - nearCount}</SectionTitle>}
            <ListRow onClick={() => { const b = bboxOf([fc([f])]); if (b) flyTo(b, String(p.id), 8); }} lead={<Disc color={H?.color ?? GREY}><H.icon size={14} /></Disc>}
              title={p.label} sub={`${day(p.period_start)} to ${day(p.period_end)}${p.props?.places ? ` · ${String(p.props.places).slice(0, 60)}` : ""}`} />
            </div>
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
      {periodRow}
      <div className="thin-scroll -mr-2 flex flex-1 flex-col gap-2.5 overflow-y-auto px-0.5 pb-1 pr-2">
        {!exp && !err && <p className="text-sm text-muted"><span className="dots">Checking exposure</span></p>}
        {exp && open.kind === "zone" && <p className="text-xs text-muted">{exp.names[0]} with {exp.names[1]}</p>}
        {exp && (
          <div className="card-still px-3 py-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Affected days in this period</div>
            <div className="font-logo text-2xl font-semibold tabular-nums">{period === "now7" ? exp.affected_days.forecast : range(exp.affected_days.low, exp.affected_days.high)}</div>
            <div className="text-xs leading-snug text-muted">{period === "now7" ? `Days with an active alert or outlook over the works. A typical week here sees ${range(exp.affected_days.low, exp.affected_days.high)}.` : `Typical days with a work-affecting event, across ${exp.counties} count${exp.counties === 1 ? "y" : "ies"} under the works.`}</div>
          </div>
        )}
        {exp?.hazards.map((h) => {
          const H = HAZARD[h.hazard];
          return (
            <div key={h.hazard} className="card-still px-3 py-2.5">
              <div className="flex items-center gap-2">
                <Disc color={H.color}><H.icon size={13} /></Disc>
                <span className="min-w-0 flex-1 text-sm font-semibold">{h.label}</span>
                <span className="text-sm font-semibold tabular-nums">{period === "now7" ? `${h.affected_days.forecast} d` : `${range(h.affected_days.low, h.affected_days.high)} d`}</span>
              </div>
              <div className="mt-1 text-xs leading-snug text-muted">{h.why}</div>
              {h.live.filter((x) => !x.product.startsWith("cpc_")).map((x) => <div key={x.id} className="mt-1.5 rounded-xl bg-soft px-2.5 py-1 text-xs">{x.label} · {day(x.from)} to {day(x.to)}</div>)}
              {h.leans.map((l) => <div key={l} className="mt-1.5 rounded-xl bg-grape-soft px-2.5 py-1 text-xs">Lean: {l}</div>)}
            </div>
          );
        })}
        {exp && !exp.hazards.length && <p className="rounded-2xl border-2 border-save/30 bg-save-soft/60 px-3 py-2 text-sm text-save">No work-affecting hazard touches this in the period.</p>}
        {exp?.cost && exp.cost.total.high > 0 && (
          <div className="rounded-2xl border-2 border-warn/25 bg-warn-soft/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-faint">Expected extra cost</span>
              <Chip tone="warn">Estimate</Chip>
            </div>
            <div className="font-logo text-2xl font-semibold tabular-nums text-warn">{money(exp.cost.total)}</div>
            <div className="text-xs leading-snug text-muted">Idle crew and equipment on affected days {when(period, month)}, plus storm-rate labor after big events.</div>
            <div className="mt-2 flex flex-col gap-1">
              {(exp.cost.kind === "zone" ? exp.cost.sites.flatMap((s) => s.items.map((i) => ({ ...i, site: s.name }))) : exp.cost.items.map((i) => ({ ...i, site: "" })))
                .sort((a, b) => b.total.high - a.total.high).slice(0, 6).map((i, n) => (
                <div key={n} className="flex items-center gap-2 text-xs">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: HAZARD[i.hazard]?.color ?? GREY }} />
                  <span className="min-w-0 flex-1 truncate">{i.label}{i.site ? ` · ${i.site.slice(0, 28)}` : ""} · {range(i.days.low, i.days.high)} d · {i.option.high === "demob" ? "demobilize and return" : "hold on standby"}</span>
                  <span className="font-semibold tabular-nums">{money(i.total)}</span>
                </div>
              ))}
            </div>
            <button onClick={() => setShowSources((v) => !v)} className="mt-2 text-[11px] font-semibold text-grape underline">{showSources ? "Hide sources" : "Sources and assumptions"}</button>
            {showSources && (
              <div className="mt-1 flex flex-col gap-1">
                {exp.cost.assumptions.map((k) => sourced[k]).filter(Boolean).map((a) => (
                  <div key={a.label} className="rounded-xl bg-white px-2 py-1 text-[11px]">
                    <span className="font-semibold">{a.label}</span> {a.low === a.high ? usd(a.low) : `${usd(a.low)} to ${usd(a.high)}`} <span className="text-muted">{a.unit}</span>
                    {!a.verified && <span className="ml-1 rounded-full bg-warn-soft px-1.5 text-[10px] font-semibold text-warn">Estimate</span>}
                    <div className="text-faint">{a.url ? <a href={a.url} target="_blank" rel="noreferrer" className="underline">{a.source}</a> : a.source}{a.page ? `, ${a.page.slice(0, 80)}` : ""}</div>
                  </div>
                ))}
                <p className="px-1 text-[11px] text-faint">{exp.cost.method}</p>
              </div>
            )}
          </div>
        )}
        {exp?.coordination && (
          <div className="rounded-2xl border-2 border-save/30 bg-save-soft/60 px-3 py-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">Coordinating with {company(exp.coordination.partners.find((p) => p !== me.company) ?? "")?.short ?? "the neighbor"}</div>
            <div className="font-logo text-2xl font-semibold tabular-nums text-save">{exp.coordination.savings.high > 0 ? `saves ${money(exp.coordination.savings)}` : "no shared weather days"}</div>
            <div className="mt-1.5 grid grid-cols-2 gap-1 text-xs">
              <span className="text-muted">Separately</span><span className="text-right font-semibold tabular-nums">{money(exp.coordination.separate)}</span>
              <span className="text-muted">Together</span><span className="text-right font-semibold tabular-nums">{money(exp.coordination.coordinated)}</span>
            </div>
            <p className="mt-1.5 text-xs leading-snug text-muted">One standby crew and yard covers both sites on {range(exp.coordination.items[0]?.shared_days.low ?? 0, exp.coordination.items[0]?.shared_days.high ?? 0)} shared affected days.</p>
            {exp.coordination.one_off.length > 0 && (
              <p className="mt-1 text-xs text-muted">Plus one-off, per project: {exp.coordination.one_off.map((o) => `${o.name} ${usd(o.low)} to ${usd(o.high)}`).join("; ")}.</p>
            )}
            {exp.coordination.best_months.length > 0 && (
              <p className="mt-1.5 text-xs">
                <span className="font-semibold">Cheapest months to work the pair:</span> {exp.coordination.best_months.map((m) => m.label).join(", ")}
                {exp.coordination.best_months[0].saves_vs_period.high > 0 && ` (saves ${money(exp.coordination.best_months[0].saves_vs_period)} per 30 days vs ${when(period, month).replace("in a typical ", "")})`}
              </p>
            )}
          </div>
        )}
        {exp && <p className="px-1 text-[11px] text-faint">{exp.method}</p>}
      </div>
    </>
  );

  return <Split map={<MapPane scene={scene} fit={fit} onPick={pick}>{legend}</MapPane>} side={side ?? (open ? detail : list)} />;
}
