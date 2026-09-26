import { useEffect, useState } from "react";
import { beaver, onSay, type Line } from "./mascot";

// the beaver's speech bubble: one short line, gone after a few seconds
export default function Speech({ className }: { className?: string }) {
  const [line, setLine] = useState<Line | null>(null);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => onSay((l) => { setLine(l); setLeaving(false); }), []);

  useEffect(() => {
    if (!line) return;
    const ms = Math.min(6000, 2200 + line.text.length * 45);  // longer lines stay a bit longer
    const fade = setTimeout(() => setLeaving(true), ms);
    const gone = setTimeout(() => { setLine(null); beaver("idle"); }, ms + 250);
    return () => { clearTimeout(fade); clearTimeout(gone); };
  }, [line]);

  if (!line) return null;
  return (
    <div className={`pointer-events-none ${className ?? ""}`} role="status" aria-live="polite">
      <div key={line.id} className={`speech ${leaving ? "speech-out" : "speech-in"}`}>{line.text}</div>
    </div>
  );
}
