import { HeartHandshake, Truck } from "lucide-react";
import { useEffect, useState } from "react";
import { stormApi, type CrewRoute, type RestorationPlan as Plan, type Scenario } from "../api-storm";
import { etTime } from "./StormBriefing";
import { Empty, Section } from "./ui";
import { Bubble, NumberField, Segmented, Slider } from "./ui-plan";

type Props = { at: string; scenario: Scenario; onSelectSite?: (lon: number, lat: number) => void; onFly?: (bbox: [number, number, number, number]) => void };

export default function RestorationPlan({ at, scenario, onSelectSite, onFly }: Props) {
  const [mode, setMode] = useState<"mutual" | "alone">("mutual");
  const [crews, setCrews] = useState({ gpc: 8, desc: 4 });
  const [maxDrive, setMaxDrive] = useState(90);
  const [data, setData] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => {  // solving takes a few seconds, so wait for the clock to settle
      setBusy(true); setError(null);
      stormApi.restoration(at, scenario, mode === "mutual", { crews_gpc: crews.gpc, crews_desc: crews.desc, max_drive_min: maxDrive })
        .then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false));
    }, 500);
    return () => clearTimeout(id);
  }, [at, scenario, mode, crews, maxDrive]);

  if (error) return <Empty title="The crew plan could not load">{error}</Empty>;
  if (!data) return <div className="px-5 py-6 text-[14px] text-muted">Planning repair crews…</div>;
  if (!data.jobs) return <Empty title="No repairs to plan yet">{data.headline}</Empty>;

  const s = data.summary!;
  const moves = (data.explanations ?? []).filter((x) => x.cross_utility);
  const routeBox = (r: CrewRoute): [number, number, number, number] => {
    const xs = [r.yard.lon, ...r.jobs.map((j) => j.lon)], ys = [r.yard.lat, ...r.jobs.map((j) => j.lat)];
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  };
  return (
    <div className="space-y-4 px-5 pb-5 pt-4">
      <div>
        <div className="flex items-center gap-2 text-[13px] font-semibold text-desc"><Truck size={16} /> After the storm, {data.jobs} repair jobs {busy && <span className="text-faint">updating…</span>}</div>
        <h2 className="mt-1 text-[20px] font-semibold leading-snug">{data.headline}</h2>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Bubble label="Each utility alone" value={`${s.alone.done_hours} h`} sub={`avg wait ${s.alone.avg_wait_hours} h`} />
        <Bubble tone="save" label="With mutual aid" value={`${s.mutual_aid.done_hours} h`} sub={`avg wait ${s.mutual_aid.avg_wait_hours} h`} />
      </div>

      {moves.length > 0 && mode === "mutual" && (
        <section>
          <h3 className="flex items-center gap-2 text-[16px] font-semibold"><HeartHandshake size={17} className="text-save" /> Crews helping the other utility
            <span className="text-[13px] font-medium text-faint">{moves.length}</span></h3>
          <ul className="mt-2 space-y-1.5">
            {moves.map((x) => {
              const job = data.routes?.flatMap((r) => r.jobs).find((j) => j.job_id === x.job_id);
              return (
                <li key={x.job_id}>
                  <button onClick={() => job && onSelectSite?.(job.lon, job.lat)} className="w-full rounded-2xl bg-save-soft px-3.5 py-2.5 text-left text-[14px] text-ink hover:brightness-[0.98]">
                    {x.sentence}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <div className="flex items-center justify-between">
        <h3 className="text-[16px] font-semibold">Crew routes</h3>
        <Segmented value={mode} options={[["mutual", "Mutual aid"], ["alone", "Each alone"]]} onChange={setMode} />
      </div>
      <ul className="space-y-2">
        {(data.routes ?? []).map((r) => (
          <li key={r.crew} className="rounded-2xl bg-soft px-3.5 py-3">
            <button onClick={() => onFly?.(routeBox(r))} className="flex w-full items-center justify-between text-left">
              <span className="flex items-center gap-2 text-[14px] font-semibold">
                <span className={`h-2.5 w-2.5 rounded-full ${r.org === "desc" ? "bg-desc" : "bg-gpc"}`} />{r.crew}
              </span>
              <span className="text-[12px] text-muted">from {r.yard.county}</span>
            </button>
            <ol className="mt-1.5 space-y-1">
              {r.jobs.map((j) => (
                <li key={j.job_id}>
                  <button onClick={() => onSelectSite?.(j.lon, j.lat)} className="flex w-full items-start gap-2 rounded-xl px-1 py-0.5 text-left text-[13px] hover:bg-white">
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${j.org === "desc" ? "bg-desc" : "bg-gpc"}`} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{j.name.replace(/^Restore /, "")}</span>
                      <span className="text-muted">{etTime(j.start)} to {etTime(j.end)}, {j.drive_min} min drive{j.cross_utility ? ", helping the other utility" : ""}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </li>
        ))}
      </ul>

      <Section title="Why each crew went where it did" count={(data.explanations ?? []).length}>
        <ul className="space-y-1.5 text-[13px] text-muted">
          {(data.explanations ?? []).map((x) => <li key={x.job_id}>{x.sentence}</li>)}
        </ul>
      </Section>

      <Section title="Assumptions">
        <div className="space-y-3 text-[14px]">
          <label className="flex items-center justify-between">Georgia Power repair crews
            <NumberField value={crews.gpc} min={1} max={40} onChange={(n) => setCrews((c) => ({ ...c, gpc: n }))} title="Georgia Power crews" /></label>
          <label className="flex items-center justify-between">Dominion Energy SC repair crews
            <NumberField value={crews.desc} min={1} max={40} onChange={(n) => setCrews((c) => ({ ...c, desc: n }))} title="DESC crews" /></label>
          <Slider label="Longest drive to help the other utility" value={maxDrive} unit="min" min={15} max={180} onChange={setMaxDrive} />
          <p className="text-[12px] text-faint">Crew counts, repair hours and yard spots are planning assumptions. Damage comes from real Helene reports, drives from road routing.</p>
        </div>
      </Section>
    </div>
  );
}
