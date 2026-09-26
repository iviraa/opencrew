import * as THREE from "three";

// three-step toon ramp: shadow, mid, lit
function ramp() {
  const g = new THREE.DataTexture(new Uint8Array([110, 190, 255]), 3, 1, THREE.RedFormat);
  g.minFilter = THREE.NearestFilter;
  g.magFilter = THREE.NearestFilter;
  g.generateMipmaps = false;
  g.needsUpdate = true;
  return g;
}

// soft crosshatch for the paddle tail
function hatch() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const x = c.getContext("2d")!;
  x.fillStyle = "#ffffff";
  x.fillRect(0, 0, 128, 128);
  x.strokeStyle = "rgba(60,30,10,0.35)";
  x.lineWidth = 5;
  for (let i = -128; i < 256; i += 26) {
    x.beginPath(); x.moveTo(i, 0); x.lineTo(i + 128, 128); x.stroke();
    x.beginPath(); x.moveTo(i + 128, 0); x.lineTo(i, 128); x.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function makeMaterials() {
  const gradientMap = ramp();
  const toon = (color: string, extra: THREE.MeshToonMaterialParameters = {}) => new THREE.MeshToonMaterial({ color, gradientMap, ...extra });
  return {
    fur: toon("#c98a54"),
    furDark: toon("#a9683a"),
    cream: toon("#f6dcb8"),
    innerEar: toon("#e7a98a"),
    nose: toon("#4a2616"),
    mouth: toon("#3a1a0e"),
    tongue: toon("#ff7d8f"),
    tooth: toon("#fffaf0"),
    brow: toon("#5a3019"),
    tail: toon("#8a5431", { map: hatch() }),
    hat: toon("#ffc62e"),
    hatRidge: toon("#f2a91a"),
    eye: new THREE.MeshStandardMaterial({ color: "#1f120c", roughness: 0.12, metalness: 0 }),
    white: new THREE.MeshBasicMaterial({ color: "#ffffff" }),
    shine: new THREE.MeshBasicMaterial({ color: "#fffbe8", transparent: true, opacity: 0.85 }),
    blush: new THREE.MeshBasicMaterial({ color: "#ff9fb2", transparent: true, opacity: 0.7, depthWrite: false }),
    dot: new THREE.MeshToonMaterial({ color: "#ffffff", gradientMap }),
  };
}

export type Mats = ReturnType<typeof makeMaterials>;
