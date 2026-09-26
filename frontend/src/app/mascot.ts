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

// short lines the beaver says in the bubble beside it
export type Line = { text: string; id: number };
const talkers = new Set<(l: Line) => void>();
let lines = 0;

export function say(text: string, mood: Mood = "talking") {
  beaver(mood);
  lines += 1;
  talkers.forEach((f) => f({ text, id: lines }));
}

export function onSay(f: (l: Line) => void) {
  talkers.add(f);
  return () => { talkers.delete(f); };
}
