// tiny event bus so any screen can make the beaver react
export type Mood = "idle" | "thinking" | "talking" | "wave" | "happy" | "surprised" | "sad" | "nod";
export const SHORT_MOODS: Mood[] = ["wave", "happy", "surprised", "sad", "nod"];  // play once, then back to the base mood

const listeners = new Set<(m: Mood) => void>();

export function beaver(m: Mood) {
  listeners.forEach((f) => f(m));
}

export function onBeaver(f: (m: Mood) => void) {
  listeners.add(f);
  return () => { listeners.delete(f); };
}
