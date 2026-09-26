import type { ReactNode } from "react";

export function Bubble({ label, value, sub, tone = "plain", compact = false }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "plain" | "save" | "desc" | "gpc" | "warn"; compact?: boolean }) {
  const bg = { plain: "bg-soft", save: "bg-save-soft", desc: "bg-desc-soft", gpc: "bg-gpc-soft", warn: "bg-warn-soft" }[tone];
  const ink = { plain: "text-ink", save: "text-save", desc: "text-desc", gpc: "text-[#d93b3b]", warn: "text-warn" }[tone];
  return (
    <div className={`min-w-0 rounded-[18px] ${compact ? "px-3.5 py-2" : "px-4 py-3"} ${bg}`}>
      <div className="truncate text-[13px] text-muted">{label}{compact && <span className={`display ml-2 text-[18px] font-semibold ${ink}`}>{value}</span>}</div>
      {!compact && <div className={`display mt-0.5 truncate text-[22px] font-semibold leading-tight ${ink}`}>{value}</div>}
      {sub && <div className="mt-0.5 truncate text-[12px] text-muted" title={typeof sub === "string" ? sub : undefined}>{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-full bg-soft p-1 ring-1 ring-line">
      {options.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)} aria-pressed={value === v}
          className={`rounded-full px-3.5 py-1 text-[13px] font-semibold transition ${value === v ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink"}`}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function Slider({ label, value, unit, min = 0, max, onChange }: { label: string; value: number; unit: string; min?: number; max: number; onChange: (n: number) => void }) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between text-[14px]">
        <span className="text-ink">{label}</span>
        <span className="display font-semibold text-desc">{value} {unit}</span>
      </div>
      <input type="range" min={min} max={max} value={value} onChange={(e) => onChange(Number(e.target.value))} className="mt-1 w-full accent-[#2f6bff]" />
    </label>
  );
}

export function NumberField({ value, onChange, min, max, step, title, width = "w-16" }: { value: number; onChange: (n: number) => void; min?: number; max?: number; step?: number; title?: string; width?: string }) {
  return (
    <input type="number" value={value} min={min} max={max} step={step} title={title} aria-label={title}
      onChange={(e) => onChange(Number(e.target.value))}
      className={`${width} rounded-full bg-surface px-3 py-1 text-[13px] ring-1 ring-line focus:outline-none focus:ring-2 focus:ring-desc`} />
  );
}
