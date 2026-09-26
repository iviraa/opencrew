import { ChevronDown, X } from "lucide-react";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { Tier } from "../api";
import { FAR_COLOR, TIER_COLOR, TIER_INK, TIER_LABEL, TIER_SOFT } from "../format";

type Variant = "primary" | "soft" | "ghost" | "save";
const VARIANT: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-[#2a3563] shadow-float",
  soft: "bg-soft text-ink ring-1 ring-line hover:bg-white",
  ghost: "text-muted hover:bg-soft hover:text-ink",
  save: "bg-save text-white hover:brightness-105",
};

export function Button({ variant = "soft", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-full px-4 py-2 text-[14px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${VARIANT[variant]} ${className}`} />
  );
}

export function IconButton({ label, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return <button aria-label={label} title={label} {...rest} className={`grid h-9 w-9 place-items-center rounded-full text-muted transition hover:bg-soft hover:text-ink ${className}`} />;
}

export function CloseButton({ onClick }: { onClick: () => void }) {
  return <IconButton label="Close" onClick={onClick}><X size={18} /></IconButton>;
}

export function TierPill({ tier, far = false, size = "md" }: { tier: Tier; far?: boolean; size?: "sm" | "md" }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-semibold ${size === "sm" ? "px-2.5 py-0.5 text-[12px]" : "px-3 py-1 text-[13px]"}`}
      style={far ? { background: "#eef1f7", color: "#5e6a8a" } : { background: TIER_SOFT[tier], color: TIER_INK[tier] }}>
      <span className="h-2 w-2 rounded-full" style={{ background: far ? FAR_COLOR : TIER_COLOR[tier] }} />
      {far ? "Too far by road" : TIER_LABEL[tier]}
    </span>
  );
}

export function Chip({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "warn" | "save" }) {
  const style = { plain: "bg-soft text-muted ring-1 ring-line", warn: "bg-warn-soft text-warn", save: "bg-save-soft text-save" }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-semibold ${style}`}>{children}</span>;
}

export function PairBubble({ a, b }: { a: string; b: string }) {
  return (  // the brand element: a blue shore and a coral shore joined in one bubble
    <div className="flex min-w-0 flex-col gap-1">
      <span className="flex min-w-0 items-center gap-2 text-[14px] font-semibold leading-snug"><span className="h-2.5 w-2.5 shrink-0 rounded-full bg-desc ring-4 ring-desc-soft" /><span className="truncate">{a}</span></span>
      <span className="flex min-w-0 items-center gap-2 text-[14px] font-semibold leading-snug"><span className="h-2.5 w-2.5 shrink-0 rounded-full bg-gpc ring-4 ring-gpc-soft" /><span className="truncate">{b}</span></span>
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: string; tone?: "warn" | "save" }) {
  const color = tone === "warn" ? "text-warn" : tone === "save" ? "text-save" : "text-ink";
  return (
    <div className="rounded-2xl bg-soft px-4 py-3">
      <div className="text-[13px] text-muted">{label}</div>
      <div className={`display mt-0.5 text-[20px] font-semibold ${color}`}>{value}</div>
      {hint && <div className="mt-0.5 text-[12px] text-faint">{hint}</div>}
    </div>
  );
}

export function Section({ title, children, defaultOpen = false, count }: { title: string; children: ReactNode; defaultOpen?: boolean; count?: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="border-t border-line">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-center justify-between py-3.5 text-left">
        <span className="display text-[16px] font-semibold">{title}{count != null && <span className="ml-2 text-[13px] font-medium text-faint">{count}</span>}</span>
        <ChevronDown size={18} className={`text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="pb-4">{children}</div>}
    </section>
  );
}

export function Sheet({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`flex h-full flex-col overflow-hidden rounded-[var(--radius-bubble)] bg-surface shadow-float ${className}`}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-6 py-10 text-center">
      <div className="display text-[17px] font-semibold">{title}</div>
      {children && <div className="mt-1 text-[14px] text-muted">{children}</div>}
    </div>
  );
}
