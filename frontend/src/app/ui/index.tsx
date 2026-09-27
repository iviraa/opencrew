import { ChevronDown, MapPin } from "lucide-react";
import { useId, useState } from "react";

export * from "./format";

// ---------- Card: every chat hand-over sits in one of these ----------
export function Card({ icon, title, sub, right, children, className = "", busy }: {
  icon?: React.ReactNode; title?: React.ReactNode; sub?: React.ReactNode; right?: React.ReactNode; children?: React.ReactNode; className?: string; busy?: boolean;
}) {
  return (
    <div className={`pop-in flex flex-col gap-2 rounded-2xl border-2 border-pen bg-white p-2.5 shadow-[3px_3px_0_var(--color-pen)] ${busy ? "opacity-70" : ""} ${className}`}>
      {(title || icon) && (
        <div className="flex items-start gap-2">
          {icon && <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-grape-soft text-grape">{icon}</span>}
          <div className="min-w-0 flex-1">
            {title && <div className="text-sm font-semibold leading-snug">{title}</div>}
            {sub && <div className="mt-0.5 text-[11px] leading-snug text-muted">{sub}</div>}
          </div>
          {right && <div className="flex shrink-0 items-center gap-1">{right}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

// ---------- Drawer: a section that folds away so a card stays short ----------
export function Drawer({ title, summary, icon, defaultOpen = false, children, className = "", onToggle }: {
  title: React.ReactNode; summary?: React.ReactNode; icon?: React.ReactNode; defaultOpen?: boolean; children: React.ReactNode; className?: string; onToggle?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={`rounded-xl border-2 border-line ${className}`}>
      <button type="button" onClick={() => { setOpen(!open); onToggle?.(!open); }} aria-expanded={open} aria-controls={id}
        className="flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-left hover:bg-soft">
        {icon && <span className="shrink-0 text-grape">{icon}</span>}
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-semibold leading-snug">{title}</span>
          {summary && <span className="block truncate text-[11px] text-muted">{summary}</span>}
        </span>
        <ChevronDown size={15} className={`shrink-0 text-muted transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      <div id={id} className="grid transition-[grid-template-rows] duration-200 ease-out" style={{ gridTemplateRows: open ? "1fr" : "0fr" }}>
        <div className="min-h-0 overflow-hidden">
          <div className="flex flex-col gap-1.5 border-t-2 border-line px-2.5 py-2">{children}</div>
        </div>
      </div>
    </div>
  );
}

// ---------- Stat: one number with its label, in a row of equals ----------
export type Tone = "good" | "bad" | "flat" | "info";
const VALUE_TONE: Record<Tone, string> = { good: "text-save", bad: "text-warn", flat: "text-ink", info: "text-grape" };

export function Stat({ label, value, note, tone = "flat", big }: { label: React.ReactNode; value: React.ReactNode; note?: React.ReactNode; tone?: Tone; big?: boolean }) {
  return (
    <div className="min-w-0 rounded-xl bg-soft px-2.5 py-1.5">
      <div className="line-clamp-2 text-[10px] font-semibold uppercase leading-tight tracking-wide text-faint" title={typeof label === "string" ? label : undefined}>{label}</div>
      <div className={`display truncate font-logo font-semibold leading-tight ${big ? "text-xl" : "text-base"} ${VALUE_TONE[tone]}`}>{value}</div>
      {note && <div className="truncate text-[11px] leading-snug text-muted">{note}</div>}
    </div>
  );
}

export function StatRow({ items, cols }: { items: { label: React.ReactNode; value: React.ReactNode; note?: React.ReactNode; tone?: Tone }[]; cols?: 2 | 3 | 4 }) {
  if (!items.length) return null;
  const n = cols ?? (items.length >= 3 ? 3 : (items.length as 2 | 3));
  const grid = n === 4 ? "grid-cols-4" : n === 3 ? "grid-cols-3" : "grid-cols-2";
  return <div className={`grid gap-1.5 ${grid}`}>{items.map((s, i) => <Stat key={i} {...s} />)}</div>;
}

// ---------- Chip: a status word in a soft pill ----------
export type ChipTone = "neutral" | "good" | "warn" | "info" | "amber" | "danger";
const CHIP: Record<ChipTone, string> = {
  neutral: "bg-soft text-muted", good: "bg-save-soft text-save", warn: "bg-warn-soft text-warn", info: "bg-grape-soft text-grape",
  amber: "bg-crew-soft text-[#8a5a00]", danger: "bg-[#ffe8e8] text-[#c23b3b]",
};
export function Chip({ tone = "neutral", icon, children, title, style }: { tone?: ChipTone; icon?: React.ReactNode; children: React.ReactNode; title?: string; style?: React.CSSProperties }) {
  return <span title={title} style={style} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold leading-tight ${CHIP[tone]}`}>{icon}{children}</span>;
}

// ---------- Pill: the buttons at the foot of a card ----------
export function Pill({ onClick, children, primary, icon, disabled, pressed, title, className = "", grow }: {
  onClick?: () => void; children?: React.ReactNode; primary?: boolean; icon?: React.ReactNode; disabled?: boolean; pressed?: boolean; title?: string; className?: string; grow?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-pressed={pressed} title={title} aria-label={children ? undefined : title}
      className={`inline-flex items-center justify-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold transition disabled:opacity-40 ${grow ? "flex-1" : ""} ${
        primary ? "bg-grape text-white hover:bg-grape-deep" : pressed ? "border-2 border-pen bg-crew-soft" : "border-2 border-line hover:border-pen"} ${className}`}>
      {icon}{children}
    </button>
  );
}

// ---------- RefLink: an overlap or site named in text, tap to open it on the map ----------
export const REF_CLASS = "ref-link inline-flex items-center gap-0.5 rounded-md px-1 -mx-0.5 font-semibold text-grape underline decoration-grape/40 underline-offset-2 hover:bg-grape-soft focus-visible:bg-grape-soft";
export function RefLink({ id, onOpen, children, title }: { id: number; onOpen?: (id: number) => void; children?: React.ReactNode; title?: string }) {
  if (!onOpen) return <span className="font-semibold">{children ?? `#${id}`}</span>;
  return (
    <button type="button" onClick={() => onOpen(id)} title={title ?? `Open overlap #${id} on the map`} className={REF_CLASS}>
      <MapPin size={11} className="shrink-0" />{children ?? `#${id}`}
    </button>
  );
}

// ---------- Prose: the short sentences a card leads with ----------
export function Lead({ children }: { children: React.ReactNode }) {
  return <p className="text-[13px] leading-snug text-ink">{children}</p>;
}
export function Note({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "warn" | "good" }) {
  const c = tone === "warn" ? "text-warn" : tone === "good" ? "text-save" : "text-muted";
  return <p className={`text-[11px] leading-snug ${c}`}>{children}</p>;
}
export function Row({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`flex flex-wrap items-center gap-1.5 ${className}`}>{children}</div>;
}
