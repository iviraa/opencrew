import { AlertTriangle, MapPin, Tent, Users, Wind } from "lucide-react";
import { useEffect, useState } from "react";
import { stormApi, type Briefing, type PauseSite, type Scenario } from "../api-storm";
import { Empty, Section } from "./ui";
import { Bubble, Slider } from "./ui-plan";

type Props = { at: string; scenario: Scenario; onSelectSite?: (lon: number, lat: number) => void; onFly?: (bbox: [number, number, number, number]) => void };

const ORG_TONE: Record<string, "desc" | "gpc"> = { desc: "desc", gpc: "gpc" };
export const etTime = (iso: string) =>
  new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "2-digit" }) + " ET";
const hoursText = (h: number) => (h <= 0 ? "now" : h < 1 ? "within the hour" : `in ${Math.round(h)} h`);

export default function StormBriefing({ at, scenario, onSelectSite }: Props) {
  const [data, setData] = useState<Briefing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [margin, setMargin] = useState(12);
  const [perSub, setPerSub] = useState(0.2);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => {  // the replay clock moves fast, so wait for it to settle
      setError(null);
      stormApi.briefing(at, scenario, { safety_margin_h: margin, crews_per_substation: perSub }).then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }, 300);
    return () => clearTimeout(id);
  }, [at, scenario, margin, perSub]);

  if (error) return <Empty title="The briefing could not load">{error}</Empty>;
  if (!data) return <div className="px-5 py-6 text-[14px] text-muted">Reading the forecast…</div>;
  if (!data.storm) return <Empty title="No storm in the forecast">{data.reason ?? "Nothing to brief right now."} Crews and planned work carry on as usual.</Empty>;

  const s = data.storm;
  const pause = data.pause ?? [];
  const shown = showAll ? pause : pause.slice(0, 5);
  return (
    <div className="space-y-4 px-5 pb-5 pt-4">
      <div>
        <div className="flex items-center gap-2 text-[13px] font-semibold text-warn"><Wind size={16} /> Before the storm, advisory {s.advisory}</div>
        <h2 className="mt-1 text-[21px] font-semibold leading-snug">{data.headline}</h2>
        <p className="mt-1 text-[13px] text-muted">Forecast issued {etTime(s.issued)}. Wind zones use {s.radii_source}.</p>
      </div>

      <div className="text-[13px] font-semibold text-muted">Substations in damaging winds</div>
      <div className="grid grid-cols-2 gap-2">
        {(data.likely_hit ?? []).map((h) => (
          <Bubble key={h.org} tone={ORG_TONE[h.org] ?? "plain"} label={h.name} value={h.damaging_winds}
            sub={h.hurricane_winds ? `${h.hurricane_winds} of them hurricane-force` : `${h.tropical_storm_winds} in the wind zone`} />
        ))}
      </div>
      {(data.likely_hit ?? []).some((h) => h.counties.length) && (
        <p className="text-[13px] text-muted">
          Hardest hit: {(data.likely_hit ?? []).flatMap((h) => h.counties.slice(0, 2).map((c) => `${c.county} (${c.substations})`)).join(", ")}.
        </p>
      )}

      <section>
        <h3 className="flex items-center gap-2 text-[16px] font-semibold"><AlertTriangle size={17} className="text-warn" /> Pause these work sites
          <span className="text-[13px] font-medium text-faint">{pause.length}</span></h3>
        {pause.length === 0 && <p className="mt-1 text-[14px] text-muted">No active construction sits in the storm's path.</p>}
        <ul className="mt-2 space-y-1.5">
          {shown.map((p) => <PauseRow key={p.job_id} p={p} onClick={() => onSelectSite?.(p.lon, p.lat)} />)}
        </ul>
        {pause.length > 5 && (
          <button onClick={() => setShowAll((v) => !v)} className="mt-2 text-[13px] font-semibold text-desc hover:underline">
            {showAll ? "Show fewer" : `Show all ${pause.length}`}
          </button>
        )}
      </section>

      <section>
        <h3 className="flex items-center gap-2 text-[16px] font-semibold"><Tent size={17} className="text-save" /> Where to stage crews</h3>
        <ul className="mt-2 space-y-1.5">
          {(data.staging ?? []).map((y, i) => (
            <li key={i}>
              <button onClick={() => onSelectSite?.(y.lon, y.lat)}
                className={`w-full rounded-2xl px-3.5 py-2.5 text-left text-[14px] transition hover:brightness-[0.98] ${y.shared ? "bg-save-soft ring-1 ring-save/30" : "bg-soft"}`}>
                <span className="flex items-center gap-2 font-semibold"><MapPin size={15} className={y.shared ? "text-save" : "text-muted"} />{y.county}
                  {y.shared && <span className="rounded-full bg-save px-2 py-0.5 text-[12px] text-white">Shared by both</span>}</span>
                <span className="mt-0.5 block text-[13px] text-muted">{y.sentence}</span>
              </button>
            </li>
          ))}
        </ul>
        {(data.staging ?? []).length === 0 && <p className="mt-1 text-[14px] text-muted">No staging needed yet.</p>}
      </section>

      <section>
        <h3 className="flex items-center gap-2 text-[16px] font-semibold"><Users size={17} className="text-desc" /> Crews to have ready</h3>
        <ul className="mt-2 space-y-1 text-[14px]">
          {(data.crews ?? []).map((c) => (
            <li key={c.org} className="flex items-baseline justify-between gap-3 rounded-2xl bg-soft px-3.5 py-2">
              <span>{c.name}</span><span className="display text-[17px] font-semibold">{c.crews}</span>
            </li>
          ))}
        </ul>
      </section>

      <Section title="Assumptions">
        <div className="space-y-3">
          <Slider label="Stop crane and line work this many hours before winds" value={margin} unit="h" min={0} max={36} onChange={setMargin} />
          <Slider label="Crews per substation in damaging winds (tenths)" value={Math.round(perSub * 10)} unit="/10" min={1} max={10} onChange={(n) => setPerSub(n / 10)} />
          <p className="text-[12px] text-faint">These are planning assumptions, not utility data. Wind zones and arrival times come from the NHC forecast.</p>
        </div>
      </Section>
    </div>
  );
}

function PauseRow({ p, onClick }: { p: PauseSite; onClick: () => void }) {
  const tone = p.status === "stop now" ? "bg-gpc-soft text-[#c0392b]" : p.status === "pause soon" ? "bg-crew-soft text-[#9a5b00]" : "bg-soft text-muted";
  return (
    <li>
      <button onClick={onClick} className="w-full rounded-2xl px-3.5 py-2.5 text-left transition hover:bg-soft">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2 text-[14px] font-semibold">
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${p.org === "desc" ? "bg-desc" : "bg-gpc"}`} />
              <span className="truncate">{p.project}</span>
            </div>
            <div className="mt-0.5 text-[13px] text-muted">{p.phase[0].toUpperCase() + p.phase.slice(1)}, winds arrive {etTime(p.arrival)}</div>
          </div>
          <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${tone}`}>
            {p.status === "stop now" ? "Stop now" : `Pause ${hoursText(p.hours_left)}`}
          </span>
        </div>
      </button>
    </li>
  );
}
