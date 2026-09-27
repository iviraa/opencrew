import { useMemo } from "react";
import { linkRefs, type RefIndex } from "./refs";

// a crewly message: markdown, with overlap and site names tappable
export function RefText({ text, index, onOpen, className = "" }: { text: string; index: RefIndex; onOpen?: (id: number) => void; className?: string }) {
  const html = useMemo(() => linkRefs(text, index), [text, index]);
  return (
    <div className={className} dangerouslySetInnerHTML={{ __html: html }}
      onClick={(e) => { const b = (e.target as HTMLElement).closest<HTMLElement>("[data-ref]"); if (b && onOpen) { e.preventDefault(); onOpen(Number(b.dataset.ref)); } }} />
  );
}
