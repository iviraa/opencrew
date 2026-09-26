import { Outlines, RoundedBox } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import * as THREE from "three";
import { onBeaver, SHORT_MOODS, type Mood } from "../mascot";
import { makeMaterials } from "./materials";

const INK = "#3a2213";
const DOTS = [0.035, 0.05, 0.065];  // thinking dot sizes
const DUR: Partial<Record<Mood, number>> = { wave: 2.4, happy: 1.7, surprised: 1.6, sad: 2.6, nod: 1.3 };
const HEAD = { a: 0.64 * 1.08, b: 0.64 * 0.94, c: 0.64 * 0.95 };
const surf = (x: number, y: number) => HEAD.c * Math.sqrt(Math.max(0, 1 - (x / HEAD.a) ** 2 - (y / HEAD.b) ** 2));  // front of the head
const damp = THREE.MathUtils.damp;
const rand = (a: number, b: number) => a + Math.random() * (b - a);

type G = THREE.Group;
type M = THREE.Mesh;

function Ol({ t = 3.2 }: { t?: number }) {
  return <Outlines thickness={t} color={INK} />  // thickness is in screen pixels;
}

export type Pointer = { x: number; y: number };

export default function Model({ pointer, reduce }: { pointer: RefObject<Pointer>; reduce: boolean }) {
  const m = useMemo(() => makeMaterials(), []);
  const geo = useMemo(() => {
    const profile = new THREE.SplineCurve([
      [0, 0], [0.4, 0.02], [0.58, 0.14], [0.64, 0.34], [0.62, 0.56], [0.54, 0.8], [0.42, 1.0], [0.26, 1.16], [0, 1.24],
    ].map(([x, y]) => new THREE.Vector2(x, y))).getPoints(48);
    profile[0].x = 0;
    profile[profile.length - 1].x = 0;
    return {
      body: new THREE.LatheGeometry(profile, 48),
      sphere: new THREE.SphereGeometry(1, 40, 28),
      dome: new THREE.SphereGeometry(0.6, 48, 20, 0, Math.PI * 2, 0, Math.PI / 2),
      brim: new THREE.CylinderGeometry(0.8, 0.82, 0.05, 56),
      ridge: new THREE.TorusGeometry(0.6, 0.06, 12, 48, Math.PI),
      arc: new THREE.TorusGeometry(0.07, 0.016, 10, 28, Math.PI),
      eyeArc: new THREE.TorusGeometry(0.06, 0.019, 10, 24, Math.PI),
      grin: new THREE.CircleGeometry(0.11, 32, Math.PI, Math.PI),
      tongue: new THREE.CircleGeometry(0.06, 24, Math.PI, Math.PI),
      arm: new THREE.CapsuleGeometry(0.1, 0.28, 8, 16),
      brow: new THREE.CapsuleGeometry(0.02, 0.075, 6, 10),
      tooth: new THREE.BoxGeometry(0.05, 0.075, 0.03),
    };
  }, []);

  const root = useRef<G>(null!), body = useRef<G>(null!), head = useRef<G>(null!), hat = useRef<G>(null!);
  const armL = useRef<G>(null!), armR = useRef<G>(null!), earL = useRef<G>(null!), earR = useRef<G>(null!), tail = useRef<G>(null!);
  const eyeL = useRef<G>(null!), eyeR = useRef<G>(null!), openL = useRef<G>(null!), openR = useRef<G>(null!);
  const happyL = useRef<M>(null!), happyR = useRef<M>(null!), browL = useRef<M>(null!), browR = useRef<M>(null!);
  const smile = useRef<G>(null!), frown = useRef<M>(null!), grin = useRef<G>(null!), ooh = useRef<M>(null!), dots = useRef<G>(null!);
  const [hover, setHover] = useState(false);

  const st = useRef({
    base: "idle" as Mood, short: null as Mood | null, shortStart: 0, queued: null as Mood | null,
    nextBlink: 1.5, blinkStart: -9, double: false, nextFidget: rand(10, 16), fidget: "" as string, fidgetStart: -9,
    v: {} as Record<string, number>,
  });

  useEffect(() => {
    st.current.queued = "wave";  // hello on arrival
    return onBeaver((mood) => {
      if (SHORT_MOODS.includes(mood)) st.current.queued = mood;
      else { st.current.base = mood; st.current.short = null; }
    });
  }, []);

  useEffect(() => {
    document.body.style.cursor = hover ? "pointer" : "";
    return () => { document.body.style.cursor = ""; };
  }, [hover]);

  const click = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    st.current.queued = Math.random() < 0.5 ? "happy" : "wave";
  };

  useFrame((state, delta) => {
    const s = st.current, t = state.clock.elapsedTime, dt = Math.min(delta, 0.05), k = reduce ? 0.35 : 1;
    const v = s.v;
    const go = (key: string, target: number, lambda = 8) => (v[key] = damp(v[key] ?? target, target, lambda, dt));

    if (s.queued && t > 0.5) { s.short = s.queued; s.shortStart = t; s.queued = null; }
    if (s.short && t - s.shortStart > (DUR[s.short] ?? 2)) s.short = null;
    const mood = s.short ?? s.base;
    const p = s.short ? (t - s.shortStart) / (DUR[s.short] ?? 2) : 0;
    const is = (x: Mood) => (mood === x ? 1 : 0);

    // idle fidgets: small things so it never looks frozen
    if (t > s.nextFidget) {
      s.nextFidget = t + rand(10, 16);
      const pick = ["wave", "happy", "hat", "ear", "tail", "hat", "ear"][Math.floor(Math.random() * 7)];
      if (mood === "idle" && (pick === "wave" || pick === "happy")) { s.short = pick; s.shortStart = t; }
      else { s.fidget = pick; s.fidgetStart = t; }
    }
    const f = t - s.fidgetStart, fid = (name: string, len: number) => (s.fidget === name && f < len ? Math.sin((f / len) * Math.PI) : 0);

    // blinking, sometimes twice
    if (t > s.nextBlink) { s.blinkStart = t; s.double = Math.random() < 0.25; s.nextBlink = t + rand(2.5, 6); }
    const b = t - s.blinkStart, blink = b < 0.13 || (s.double && b > 0.22 && b < 0.35);

    const px = pointer.current?.x ?? 0, py = pointer.current?.y ?? 0;
    const talk = is("talking") * (0.5 + 0.5 * Math.sin(t * 13) * Math.sin(t * 5.3 + 1));

    // whole body: jump, hop back, sway, breathing, hover squash
    const jump = is("happy") * Math.max(0, Math.sin(p * Math.PI * 4)) * 0.2;
    const hop = is("surprised") * (p < 0.35 ? Math.sin((p / 0.35) * Math.PI) * 0.12 : 0);
    root.current.position.y = go("y", (jump + hop) * k, 18);
    root.current.position.z = go("z", -hop * 0.6 * k, 10);
    root.current.rotation.z = Math.sin(t * 0.9) * 0.035 * k + go("rz", is("sad") * -0.02 + (is("thinking") ? 0.04 : 0), 3);
    const squash = is("happy") * Math.sin(p * Math.PI * 8) * 0.05 + (hover ? -0.04 : 0);
    const breath = Math.sin(t * 2.2) * 0.018 * k;
    body.current.scale.set(go("sx", 1 - squash * 0.6, 12), go("sy", 1 + squash, 12) + breath, 1);

    // head: follows the pointer, plus mood poses
    const nod = is("nod") * Math.sin(p * Math.PI * 4) * 0.22 + is("talking") * Math.sin(t * 6) * 0.05;
    head.current.rotation.y = go("hy", THREE.MathUtils.clamp(px * 0.55, -0.55, 0.55) * (is("thinking") ? 0.3 : 1) + is("thinking") * 0.3, 5);
    head.current.rotation.x = go("hx", THREE.MathUtils.clamp(py * 0.3, -0.3, 0.3) + is("sad") * 0.32 - is("thinking") * 0.15 - is("surprised") * 0.12, 6) + nod * k;
    head.current.rotation.z = go("hz", is("thinking") * 0.2 + is("sad") * -0.08 + Math.sin(t * 0.45) * 0.07 * k, 4)
      + is("happy") * Math.sin(p * Math.PI * 4) * 0.12 * k;

    // eyes: blink, widen, droop, look
    const open = blink ? 0.06 : 1 + is("surprised") * 0.3 - is("sad") * 0.3 - is("thinking") * 0.1;
    const happyEyes = is("happy") + is("nod") > 0 && !blink ? 1 : 0;
    const eo = go("eo", open * (1 - happyEyes), blink ? 60 : 14), he = go("he", happyEyes, 14);
    for (const [g, h] of [[openL, happyL], [openR, happyR]] as const) {
      g.current.scale.set(1, Math.max(eo, 0.02), 1);
      g.current.visible = eo > 0.03;
      h.current.scale.setScalar(Math.max(he, 0.001));
      h.current.visible = he > 0.02;
    }
    const lx = go("lx", THREE.MathUtils.clamp(px, -1, 1) * 0.025 + is("thinking") * 0.03, 8);
    const ly = go("ly", THREE.MathUtils.clamp(-py, -1, 1) * 0.02 + is("thinking") * 0.04 - is("sad") * 0.02, 8);
    eyeL.current.position.set(-0.22 + lx, 0.1 + ly, surf(0.22, 0.1) - 0.02);
    eyeR.current.position.set(0.22 + lx, 0.1 + ly, surf(0.22, 0.1) - 0.02);

    // brows
    const by = go("by", 0.25 + is("surprised") * 0.07 + is("sad") * 0.02, 10);
    browL.current.position.y = by + is("thinking") * 0.05;
    browR.current.position.y = by;
    browL.current.rotation.z = Math.PI / 2 + go("bl", is("sad") * -0.45 + is("thinking") * 0.2 + is("surprised") * 0.1, 10);
    browR.current.rotation.z = Math.PI / 2 + go("br", is("sad") * 0.45 - is("surprised") * 0.1, 10);

    // mouth shapes cross-fade by scale
    const sm = go("sm", (is("idle") + is("nod") * 1.25 + is("thinking") * 0.7), 12);
    const gr = go("gr", is("wave") + is("happy"), 12);
    smile.current.scale.set(Math.max(sm, 0.001), Math.max(sm, 0.001), 1);
    smile.current.visible = sm > 0.02;
    const gy = Math.max(gr, talk * 0.9);
    grin.current.scale.set(Math.max(gr, is("talking") * 0.75, 0.001), Math.max(gy, 0.001), 1);
    grin.current.visible = gy > 0.02;
    const fr = go("fr", is("sad"), 10), oo = go("oo", is("surprised"), 14);
    frown.current.scale.setScalar(Math.max(fr * 0.75, 0.001));
    frown.current.visible = fr > 0.02;
    ooh.current.scale.set(Math.max(oo * 0.055, 0.001), Math.max(oo * 0.07, 0.001), 0.03);
    ooh.current.visible = oo > 0.02;

    // arms
    const waving = is("wave") * Math.min(1, p * 5) * (p > 0.88 ? (1 - p) / 0.12 : 1);
    const cheer = is("happy") * (0.9 + Math.sin(p * Math.PI * 4) * 0.25) + is("surprised") * 0.8;
    armR.current.rotation.z = go("ar", 0.42 + waving * 2.35 + cheer - is("sad") * 0.2, 9) + waving * Math.sin(t * 12) * 0.35 * k;
    armR.current.rotation.x = go("arx", -waving * 0.2, 9);
    armL.current.rotation.z = go("al", is("thinking") ? 2.35 : -0.42 - cheer + is("sad") * 0.2, 7);  // thinking: hand to chin
    armL.current.rotation.x = go("alx", is("thinking") * -0.9, 7);

    // ears, hat, tail
    const wig = fid("ear", 1.0) * Math.sin(f * 30) * 0.35 * k;
    earL.current.rotation.z = go("el", is("sad") * 0.5, 6) + wig;
    earR.current.rotation.z = go("er", -is("sad") * 0.5, 6) - wig;
    const lift = fid("hat", 1.2);
    hat.current.position.y = 0.3 + go("hp", is("surprised") * 0.1, 14) + lift * 0.12 * k;
    hat.current.rotation.z = 0.1 + lift * -0.25 * k;
    hat.current.rotation.x = -0.12 + go("hr", is("sad") * 0.12, 6);
    tail.current.rotation.x = -1.35 + fid("tail", 0.9) * Math.sin(f * 14) * 0.35 * k + is("happy") * Math.sin(t * 16) * 0.12 * k;

    // thinking dots
    const d = go("dots", is("thinking"), 6);
    dots.current.visible = d > 0.02;
    dots.current.children.forEach((c, i) => {
      c.scale.setScalar(Math.max(0.001, DOTS[i] * d * (0.75 + 0.25 * Math.sin(t * 4 - i * 0.9))));
      c.position.y = i * 0.12 + Math.sin(t * 3 - i) * 0.02;
    });
  });

  const eyeZ = surf(0.22, 0.1) - 0.02;
  const muzzleZ = surf(0, -0.2) - 0.14;
  const faceZ = muzzleZ + 0.3 * 0.75;

  return (
    <group ref={root} onClick={click} onPointerOver={(e) => { e.stopPropagation(); setHover(true); }} onPointerOut={() => setHover(false)}>
      <group ref={body}>
        {/* body, belly, feet */}
        <mesh geometry={geo.body} material={m.fur}><Ol /></mesh>
        <mesh geometry={geo.sphere} material={m.cream} position={[0, 0.5, 0.44]} scale={[0.38, 0.42, 0.2]} />
        {[-1, 1].map((sx) => (
          <mesh key={sx} geometry={geo.sphere} material={m.furDark} position={[sx * 0.27, 0.06, 0.4]} scale={[0.17, 0.1, 0.22]}><Ol t={2.6} /></mesh>
        ))}
        {/* tail */}
        <group ref={tail} position={[-0.4, 0.1, -0.22]} rotation={[-1.35, 0, 0.9]}>
          <RoundedBox args={[0.46, 0.8, 0.07]} radius={0.03} smoothness={3} position={[0, 0.36, 0]} material={m.tail}><Ol t={2.6} /></RoundedBox>
        </group>
        {/* arms */}
        <group ref={armL} position={[-0.47, 0.9, 0.16]}>
          <mesh geometry={geo.arm} material={m.fur} position={[0, -0.22, 0]}><Ol t={2.6} /></mesh>
        </group>
        <group ref={armR} position={[0.47, 0.9, 0.16]}>
          <mesh geometry={geo.arm} material={m.fur} position={[0, -0.22, 0]}><Ol t={2.6} /></mesh>
        </group>
      </group>

      <group ref={head} position={[0, 1.42, 0.04]}>
        <mesh geometry={geo.sphere} material={m.fur} scale={[HEAD.a, HEAD.b, HEAD.c]}><Ol /></mesh>
        {/* ears */}
        {[[-1, earL], [1, earR]].map(([sx, ref]) => (
          <group key={sx as number} ref={ref as RefObject<G>} position={[(sx as number) * 0.63, 0.14, -0.06]}>
            <mesh geometry={geo.sphere} material={m.fur} scale={[0.14, 0.14, 0.08]}><Ol t={2.4} /></mesh>
            <mesh geometry={geo.sphere} material={m.innerEar} position={[0, 0, 0.04]} scale={[0.08, 0.08, 0.05]} />
          </group>
        ))}
        {/* muzzle */}
        <mesh geometry={geo.sphere} material={m.cream} position={[0, -0.2, muzzleZ]} scale={[0.39, 0.26, 0.225]} />
        {/* eyes */}
        {[[-1, eyeL, openL, happyL], [1, eyeR, openR, happyR]].map(([sx, g, o, h]) => (
          <group key={sx as number} ref={g as RefObject<G>} position={[(sx as number) * 0.22, 0.1, eyeZ]} rotation={[0, (sx as number) * 0.32, 0]}>
            <group ref={o as RefObject<G>}>
              <mesh geometry={geo.sphere} material={m.eye} scale={[0.085, 0.1, 0.05]} />
              <mesh geometry={geo.sphere} material={m.white} position={[-0.028, 0.038, 0.045]} scale={0.026} />
              <mesh geometry={geo.sphere} material={m.white} position={[0.024, -0.03, 0.045]} scale={0.012} />
            </group>
            <mesh ref={h as RefObject<M>} geometry={geo.eyeArc} material={m.eye} position={[0, -0.02, 0.03]} visible={false} />
          </group>
        ))}
        {/* brows */}
        <mesh ref={browL} geometry={geo.brow} material={m.brow} position={[-0.22, 0.25, surf(0.22, 0.25) + 0.005]} rotation={[0, -0.3, Math.PI / 2]} />
        <mesh ref={browR} geometry={geo.brow} material={m.brow} position={[0.22, 0.25, surf(0.22, 0.25) + 0.005]} rotation={[0, 0.3, Math.PI / 2]} />
        {/* cheeks */}
        {[-1, 1].map((sx) => (
          <mesh key={sx} geometry={geo.sphere} material={m.blush} position={[sx * 0.37, -0.1, surf(0.37, -0.1) - 0.005]}
                rotation={[0, sx * 0.6, 0]} scale={[0.085, 0.06, 0.02]} />
        ))}
        {/* nose, mouth, teeth */}
        <mesh geometry={geo.sphere} material={m.nose} position={[0, -0.06, faceZ - 0.02]} scale={[0.075, 0.055, 0.05]}>
          <mesh geometry={geo.sphere} material={m.white} position={[-0.35, 0.35, 0.7]} scale={0.22} />
        </mesh>
        <group ref={smile} position={[0, -0.115, faceZ + 0.004]}>
          <mesh geometry={geo.arc} material={m.mouth} position={[-0.042, 0, 0]} rotation={[0, 0, Math.PI]} scale={0.6} />
          <mesh geometry={geo.arc} material={m.mouth} position={[0.042, 0, 0]} rotation={[0, 0, Math.PI]} scale={0.6} />
        </group>
        <mesh ref={frown} geometry={geo.arc} material={m.mouth} position={[0, -0.215, faceZ - 0.004]} visible={false} />
        <group ref={grin} position={[0, -0.13, faceZ - 0.005]} visible={false}>
          <mesh geometry={geo.grin} material={m.mouth} />
          <mesh geometry={geo.tongue} material={m.tongue} position={[0, -0.05, 0.002]} scale={[1, 0.7, 1]} />
        </group>
        <mesh ref={ooh} geometry={geo.sphere} material={m.mouth} position={[0, -0.2, faceZ - 0.01]} visible={false} scale={0.001} />
        {[-1, 1].map((sx) => (
          <mesh key={sx} geometry={geo.tooth} material={m.tooth} position={[sx * 0.027, -0.165, faceZ + 0.006]}><Ol t={1.4} /></mesh>
        ))}
        {/* hard hat */}
        <group ref={hat} position={[0, 0.3, 0]} rotation={[-0.12, 0, 0.1]}>
          <group scale={[1.17, 0.92, 1.14]}>
            <mesh geometry={geo.dome} material={m.hat}><Ol t={3} /></mesh>
            <mesh geometry={geo.ridge} material={m.hatRidge} rotation={[0, Math.PI / 2, 0]}><Ol t={2} /></mesh>
          </group>
          <mesh geometry={geo.brim} material={m.hat} position={[0, 0, 0.06]} scale={[1, 1, 1.02]}><Ol t={3} /></mesh>
          <mesh geometry={geo.sphere} material={m.shine} position={[-0.3, 0.36, 0.42]} rotation={[0.4, -0.5, 0.5]} scale={[0.1, 0.05, 0.02]} />
        </group>
        {/* thinking dots */}
        <group ref={dots} position={[0.62, 0.5, 0.2]} visible={false}>
          {DOTS.map((r, i) => (
            <mesh key={i} geometry={geo.sphere} material={m.dot} position={[i * 0.1, i * 0.12, 0]} scale={r}><Ol t={2} /></mesh>
          ))}
        </group>
      </group>
    </group>
  );
}
