// where the backend lives: same origin in dev and in the single container, VITE_API_URL when the frontend is hosted elsewhere
export const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
