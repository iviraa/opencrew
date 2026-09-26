import { CloudLightning, CloudRain, Siren, Telescope, Waves, Wind } from "lucide-react";
import { useState } from "react";
import { PRODUCT_LABEL, RISK_COLOR, riskColor, type HeadsUp, type OutlookFrame } from "../api-outlook";
import { CloseButton } from "./ui";

const ICON = { severe: CloudLightning, severe48: CloudLightning, flood: CloudRain, wind: Wind, tropical: Waves, watch: Siren };
const et = (iso: string) => new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric", hour: "numeric" });

const sentence = (t: string) => {  // the day is already the group heading
  const s = t.replace(/^(Today|Tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday): /, "");
  return s.charAt(0).toUpperCase() + s.slice(1);
};

type Props = { data: OutlookFrame | null; scenario: "none" | "helene"; onPick: (item: HeadsUp) => void };

export default function OutlookPanel({ data, scenario, onPick }: Props) {
  const [open, setOpen] = useState(true);
  const items = data?.heads_up ?? [];
  const days: [string, HeadsUp[]][] = [];
  for (const h of items) {
    const last = days[days.length - 1];
    if (last && last[0] === h.day) last[1].push(h);
    else days.push([h.day, [h]]);
  }
  const missing = Object.entries(data?.available ?? {}).filter(([, v]) => v.note);

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="inline-flex items-center gap-1.5 rounded-full bg-surface px-3.5 py-2 text-[13px] font-semibold shadow-float">
        <Telescope size={15} className="text-warn" /> Coming up this week{items.length ? ` (${items.length})` : ""}
      </button>
    );
  }
  return (
    <div className="flex max-h-full w-[380px] flex-col rounded-[20px] bg-surface px-4 py-3 shadow-float">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-[15px] font-semibold"><Telescope size={17} className="text-warn" /> Coming up this week</div>
          <div className="mt-0.5 text-[12px] text-muted">
            {data ? `Official SPC, WPC and NHC outlooks as of ${et(data.known)} ET` : "Checking the outlooks…"}
          </div>
        </div>
        <CloseButton onClick={() => setOpen(false)} />
      </div>
      {data && items.length === 0 && (
        <p className="mt-2 rounded-[14px] bg-soft px-3 py-2 text-[13px] text-muted">
          Nothing on the official outlooks touches Georgia or South Carolina in the next 7 days.
        </p>
      )}
      <div className="thin-scroll mt-2 min-h-0 flex-1 space-y-2 overflow-y-auto">
        {days.map(([day, list]) => (
          <section key={day}>
            <div className="px-1 pb-1 text-[12px] font-semibold text-faint">{day}</div>
            <ul className="space-y-1">
              {list.map((h) => {
                const Icon = ICON[h.kind] ?? CloudLightning;
                return (
                  <li key={h.id}>
                    <button onClick={() => onPick(h)} disabled={!h.bbox} title={PRODUCT_LABEL[h.product] ?? h.product}
                      className="flex w-full items-start gap-2.5 rounded-[14px] px-2.5 py-2 text-left text-[13px] leading-snug transition hover:bg-soft disabled:cursor-default disabled:hover:bg-transparent">
                      <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-white" style={{ background: riskColor(h.rank) }}>
                        <Icon size={13} />
                      </span>
                      <span>{sentence(h.text)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-2 border-t border-line pt-2 text-[12px] text-muted">
        <span>Lower risk</span>
        <span className="flex overflow-hidden rounded-full">{RISK_COLOR.map((c) => <span key={c} className="h-2 w-5" style={{ background: c }} />)}</span>
        <span>Higher</span>
        <span className="ml-auto">Dashed: storm may form</span>
      </div>
      {scenario === "helene" && missing.map(([k, v]) => (
        <p key={k} className="mt-1 text-[12px] text-faint">{PRODUCT_LABEL[k] ?? k}: {v.note}.</p>
      ))}
    </div>
  );
}
