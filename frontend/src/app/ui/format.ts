// number and unit formatting shared by every chat card, so ranges, percents and days read the same everywhere
export const usd = (n: number) => {
  const a = Math.abs(n), s = n < 0 ? "-" : "";
  return s + (a >= 1e6 ? `$${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `$${Math.round(a / 1e3)}k` : `$${Math.round(a)}`);
};
export const usdRange = (low: number, high: number) => (low === high ? usd(low) : `${usd(low)} to ${usd(high)}`);
export const pct = (v: number, digits = 0) => `${v.toFixed(digits)}%`;
export const num = (v: number, digits?: number) => (Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(digits ?? 1));
export const days = (n: number) => `${num(n)} day${n === 1 ? "" : "s"}`;
export const miles = (m: number) => `${(m / 1609.344).toFixed(m < 16093 ? 1 : 0)} mi`;
export const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
export const confidence = (v: number) => `Confidence ${Math.round((v <= 1 ? v * 100 : v))}%`;

// a value with its unit, the way a sentence would say it
export const withUnit = (v: number | string | null | undefined, unit?: string) => {
  if (typeof v !== "number") return String(v ?? "");
  if (unit === "USD" || unit === "$") return usd(v);
  if (unit === "%") return pct(v, Number.isInteger(v) ? 0 : 1);
  if (unit === "days" || unit === "day") return days(v);
  return unit && unit !== "count" ? `${num(v)} ${unit}` : num(v);
};
export const bare = (v: number | string | null | undefined, unit?: string) => (typeof v === "number" && unit !== "USD" && unit !== "$" && unit !== "%" ? num(v) : withUnit(v, unit));  // the first number of a "from A to B" pair
export const signedUnit = (d: number, unit?: string) => `${d > 0 ? "+" : d < 0 ? "−" : ""}${unit === "%" ? `${num(Math.abs(d))} pts` : withUnit(Math.abs(d), unit)}`;
export const signedPct = (p: number) => `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.round(Math.abs(p))}%`;

export const dateShort = (s: string) => new Date(s.length <= 10 ? `${s}T12:00:00` : s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
export const monthYear = (s: string) => new Date(s.length <= 10 ? `${s}T12:00:00` : s).toLocaleDateString("en-US", { month: "short", year: "numeric" });
export const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
export const capital = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
