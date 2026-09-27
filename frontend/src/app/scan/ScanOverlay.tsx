import type { Counts, Phase } from "./useScan";

const STEPS = ["Reading your project plans", "Looking for neighbors within 25 miles", "Measuring drive times", "Comparing build windows", "Estimating savings"];

// phase 1 keeps the radar and its steps; phase 2 is a quiet strip while other utilities' sites appear
export default function ScanOverlay({ phase, step, counts, color }: { phase: Phase; step: number; counts: Counts; color: string }) {
  if (phase === "radar") {
    return (
      <div className="pointer-events-none absolute inset-0 grid place-items-center bg-white/35">
        <div className="pop-in flex flex-col items-center gap-5">
          <div className="radar">
            <span className="radar-ring" /><span className="radar-ring" style={{ animationDelay: ".8s" }} /><span className="radar-ring" style={{ animationDelay: "1.6s" }} />
            <span className="blip" style={{ left: "64%", top: "30%", background: "#ff9f1c" }} />
            <span className="blip" style={{ left: "28%", top: "58%", background: color, animationDelay: ".5s" }} />
            <span className="blip" style={{ left: "52%", top: "72%", background: "#00b8a9", animationDelay: "1s" }} />
          </div>
          <div className="rounded-2xl bg-white/85 px-4 py-2 text-center">
            <div className="font-logo text-2xl font-semibold"><span className="dots">Scanning for nearby projects</span></div>
            <div key={step} className="pop-in mt-1 text-sm text-muted">{STEPS[Math.min(step, STEPS.length - 1)]}</div>
            <Tally counts={counts} />
          </div>
        </div>
      </div>
    );
  }
  if (phase === "discover") {
    return (
      <div className="pointer-events-none absolute inset-x-0 bottom-5 flex justify-center">
        <div className="pop-in flex items-center gap-3 rounded-full border-2 border-pen bg-white/95 py-1.5 pl-4 pr-5 text-sm font-semibold">
          <span className="live-dot h-2.5 w-2.5 rounded-full bg-grape" />
          <span className="dots">Finding other utilities' sites</span>
          <Tally counts={counts} inline />
        </div>
      </div>
    );
  }
  return null;
}

function Tally({ counts, inline }: { counts: Counts; inline?: boolean }) {
  const parts = [`${counts.sites} sites`, `${counts.neighbors} neighbor${counts.neighbors === 1 ? "" : "s"}`, `${counts.overlaps} overlap${counts.overlaps === 1 ? "" : "s"}`];
  if (counts.others) parts.push(`${counts.others} other utilities' sites`);
  return <span className={inline ? "text-muted" : "mt-1 block text-xs font-semibold text-muted"}>{parts.join(" · ")}</span>;
}
