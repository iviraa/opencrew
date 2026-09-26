import { ChevronDown } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { CloseButton } from "./ui";

export function Disclosure({ title, open, onToggle, children, count, id }: {
  title: string; open: boolean; onToggle: () => void; children: ReactNode; count?: ReactNode; id?: string;
}) {
  return (  // same look as Section, but the parent controls it so buttons elsewhere can open it
    <section id={id} className="scroll-mt-4 border-t border-line">
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-center justify-between py-3.5 text-left">
        <span className="display text-[16px] font-semibold">{title}{count != null && <span className="ml-2 text-[13px] font-medium text-faint">{count}</span>}</span>
        <ChevronDown size={18} className={`text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="pb-4">{children}</div>}
    </section>
  );
}

export function Modal({ title, subtitle, onClose, children, actions, width = 560 }: {
  title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; actions?: ReactNode; width?: number;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);  // capture so the app-level handler doesn't also close the panel
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/35 p-6 backdrop-blur-[2px]" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className="flex max-h-full w-full flex-col rounded-[24px] bg-surface shadow-float"
        style={{ maxWidth: width }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 px-6 pb-2 pt-5">
          <div>
            <h2 className="text-[22px] font-semibold">{title}</h2>
            {subtitle && <div className="mt-1 text-[14px] text-muted">{subtitle}</div>}
          </div>
          <div className="flex shrink-0 items-center gap-2">{actions}<CloseButton onClick={onClose} /></div>
        </div>
        <div className="thin-scroll min-h-0 overflow-y-auto px-6 pb-6">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[13px] font-semibold text-muted">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

export const inputClass = "w-full rounded-2xl bg-soft px-3.5 py-2.5 text-[14px] text-ink ring-1 ring-line placeholder:text-faint focus:bg-white focus:outline-none focus:ring-2 focus:ring-desc disabled:opacity-60";
