import { ContactShadows } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import Model, { type Pointer } from "./beaver/Model";

// the crewly mascot: a toon 3D beaver in a hard hat that reacts to beaver(mood) calls
export default function Beaver({ className }: { className?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const pointer = useRef<Pointer>({ x: 0.6, y: -0.4 });
  const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    const move = (e: PointerEvent) => {  // look at the cursor anywhere on the page
      const r = box.current?.getBoundingClientRect();
      if (!r) return;
      pointer.current = { x: (e.clientX - (r.left + r.width / 2)) / (window.innerWidth / 2), y: (e.clientY - (r.top + r.height * 0.35)) / (window.innerHeight / 2) };
    };
    window.addEventListener("pointermove", move);
    return () => window.removeEventListener("pointermove", move);
  }, []);

  return (
    <div ref={box} className={className}>
      <Canvas flat dpr={[1, 2]} camera={{ position: [0, 0, 5.8], fov: 30 }} gl={{ antialias: true }}>
        <hemisphereLight args={["#fff4e6", "#7a4fd0", 1.1]} />
        <directionalLight position={[2.5, 4, 5]} intensity={1.9} />
        <directionalLight position={[-3, 2, -3]} intensity={2.2} color="#e4d4ff" />
        <group position={[0, -1.18, 0]}>
          <Model pointer={pointer} reduce={reduce} />
          <ContactShadows position={[0, 0, 0]} opacity={0.35} blur={2.4} scale={3} far={1.2} color="#2a1450" />
        </group>
      </Canvas>
    </div>
  );
}
