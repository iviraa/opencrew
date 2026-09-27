import { useCallback, useEffect, useRef, useState } from "react";
import { api, company, type Jobs, type Me, type Overlap } from "../data";
import type { Mood } from "../mascot";

// what one scan works with: our sites, the neighbors we overlap with, everyone else nearby, and the overlaps themselves
export type ScanCtx = { center: [number, number]; radius_km: number; ours: Jobs; partners: Jobs; others: Jobs; overlaps: Overlap[] };
export type Phase = "idle" | "radar" | "discover" | "done";
export type Counts = { sites: number; neighbors: number; overlaps: number; others: number };
type Refreshed = { promoted?: { source?: string; planner?: string; name?: string }[] };

export const RADAR_MS = 3200;  // phase 1: the radar and its steps, while partners and overlaps pop in
const POP_MS = 380;  // how long a freshly found site stays enlarged
const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// size and brightness of a feature that appeared `age` ms ago: a quick pop, then normal
export function pop(age: number) {
  if (age < 0) return { scale: 0, alpha: 0 };
  const k = Math.min(1, age / POP_MS);
  return { scale: 1 + 0.9 * (1 - k) * (1 - k), alpha: Math.min(1, age / 120) };
}

function shuffle<T>(xs: T[]) {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

export function useScan(say: (text: string, mood?: Mood) => void) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [ctx, setCtx] = useState<ScanCtx | null>(null);
  const [now, setNow] = useState(0);
  const revealed = useRef(new Map<string, number>());  // feature key -> when it appeared (ms since the scan began)
  const timers = useRef<number[]>([]);
  const started = useRef(0);
  const [counts, setCounts] = useState<Counts>({ sites: 0, neighbors: 0, overlaps: 0, others: 0 });

  const clear = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => clear, []);
  const after = (ms: number, fn: () => void) => { timers.current.push(window.setTimeout(fn, ms)); };
  const t = () => performance.now() - started.current;

  const reveal = (key: string) => { if (!revealed.current.has(key)) revealed.current.set(key, t()); };
  const recount = (c: ScanCtx, me: Me) => {
    const r = revealed.current;
    const partners = new Set(c.overlaps.filter((o) => r.has(`op:${o.id}`)).map((o) => (o.a_org === me.company ? o.b_org : o.a_org)));
    setCounts({ sites: c.ours.features.length, neighbors: partners.size,
      overlaps: c.overlaps.filter((o) => r.has(`op:${o.id}`)).length, others: c.others.features.filter((f) => r.has(`j:${f.properties.id}`)).length });
  };

  const start = useCallback((me: Me, onDone: (c: ScanCtx) => void, onFail: (e: unknown) => void) => {
    clear(); revealed.current = new Map(); started.current = performance.now();
    setPhase("radar"); setCounts({ sites: 0, neighbors: 0, overlaps: 0, others: 0 }); setCtx(null);
    const fast = reduced();
    const radarMs = fast ? 400 : RADAR_MS;
    const tick = window.setInterval(() => setNow(t()), 70);
    timers.current.push(tick as unknown as number);
    const refresh = api.send<Refreshed>("/api/app/refresh/check", "POST", {}).catch(() => null);  // sources may have new editions; absent is fine
    let live: ScanCtx | null = null;
    let sayOnce = 0;

    api.get<ScanCtx>("/api/app/scan_context").then((c) => {
      live = c; setCtx(c);
      c.ours.features.forEach((f) => reveal(`j:${f.properties.id}`));  // ours were always on the map
      const linked = c.overlaps;  // best first, as the api orders them
      const step = fast ? 0 : Math.min(90, 1600 / Math.max(1, linked.length));
      const t0 = Math.max(0, 600 - t());  // let the radar spin a moment first
      linked.forEach((o, i) => after(t0 + i * step, () => {
        reveal(`j:${o.job_a}`); reveal(`j:${o.job_b}`); reveal(`op:${o.id}`);
        if (i === 0 && !sayOnce++) say(`First overlap: with ${company(o.a_org === me.company ? o.b_org : o.a_org).name}.`, "surprised");
        recount(c, me);
      }));
      const discoverAt = Math.max(radarMs, t0 + linked.length * step + 300);
      after(discoverAt - t(), () => {
        setPhase("discover");
        const others = c.others.features;
        const span = fast ? 600 : Math.min(6000, Math.max(4000, others.length * 25));
        const km = (f: (typeof others)[number]) => Number((f.properties as { distance_km?: number }).distance_km ?? NaN);
        const dmax = Math.max(1, ...others.map((f) => km(f) || 0));
        if (others.length && !fast) say("Now finding other utilities' sites nearby...", "thinking");
        others.forEach((f) => {  // scattered all around, but the cloud of new pops drifts outward from our sites
          const d = (km(f) || dmax) / dmax;
          const at = Math.min(span, Math.max(0, d * span * 0.7 + Math.random() * span * 0.5));
          after(at, () => { reveal(`j:${f.properties.id}`); recount(c, me); });
        });
        after(span + 400, () => { setPhase("done"); clearInterval(tick); onDone(live ?? c); });
      });
    }).catch((e) => { clear(); clearInterval(tick); setPhase("idle"); onFail(e); });

    refresh.then((r) => {  // a promoted edition: its new sites join the discovery
      if (!r?.promoted?.length || !live) return;
      api.get<ScanCtx>("/api/app/scan_context").then((c2) => {
        const had = new Set([...live!.ours.features, ...live!.partners.features, ...live!.others.features].map((f) => f.properties.id));
        const fresh = [...c2.ours.features, ...c2.partners.features, ...c2.others.features].filter((f) => !had.has(f.properties.id));
        live = c2; setCtx(c2);
        if (!fresh.length) return;
        const who = r.promoted![0].planner ?? r.promoted![0].source ?? r.promoted![0].name ?? "A planner";
        say(`${who} posted a new list: ${fresh.length} new project${fresh.length === 1 ? "" : "s"} near you.`, "surprised");
        shuffle(fresh).forEach((f, i) => after(i * 140, () => { reveal(`j:${f.properties.id}`); recount(c2, me); }));
      }).catch(() => {});
    });
  }, [say]);

  return { phase, ctx, now, counts, revealed: revealed.current, start };
}
