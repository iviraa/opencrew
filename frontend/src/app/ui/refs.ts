import DOMPurify from "dompurify";
import { marked } from "marked";
import { useMemo } from "react";
import type { Overlap } from "../data";
import { REF_CLASS } from "./index";

// the overlaps a message can point at: by "#id" and by the exact names of the projects on either side
export type RefIndex = { ids: Set<number>; byName: Map<string, number>; re: RegExp | null };

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const MIN_NAME = 8;  // shorter names would match ordinary words

export function buildRefIndex(overlaps: Overlap[] | null): RefIndex {
  const ids = new Set<number>(), byName = new Map<string, number>();
  for (const o of overlaps ?? []) {
    ids.add(o.id);
    for (const name of [o.a_name, o.b_name]) {
      const key = name?.trim().toLowerCase();
      if (key && key.length >= MIN_NAME && !byName.has(key)) byName.set(key, o.id);
    }
  }
  const names = [...byName.keys()].sort((a, b) => b.length - a.length).slice(0, 600);  // longest first so a longer name wins over one it contains
  const re = ids.size ? new RegExp(`#(\\d{1,7})(?!\\d)${names.length ? `|(?<![\\w])(${names.map(esc).join("|")})(?![\\w])` : ""}`, "gi") : null;
  return { ids, byName, re };
}

export const useRefIndex = (overlaps: Overlap[] | null) => useMemo(() => buildRefIndex(overlaps), [overlaps]);

const PIN = '<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/></svg>';
const SKIP = new Set(["A", "BUTTON", "CODE", "PRE"]);

// sanitized markdown with every overlap reference turned into a button that opens it; only our own markup is added after sanitizing
export function linkRefs(markdown: string, index: RefIndex): string {
  const html = DOMPurify.sanitize(marked.parse(markdown, { async: false }) as string);
  if (!index.re) return html;
  const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, "text/html");
  const root = doc.getElementById("root")!;
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    let el = n.parentElement, skip = false;
    while (el && el !== root) { if (SKIP.has(el.tagName)) { skip = true; break; } el = el.parentElement; }
    if (!skip && index.re.test(n.textContent ?? "")) texts.push(n as Text);
    index.re.lastIndex = 0;
  }
  for (const t of texts) {
    const src = t.textContent ?? "", frag = doc.createDocumentFragment();
    let last = 0;
    for (const m of src.matchAll(index.re)) {
      const id = m[1] ? Number(m[1]) : index.byName.get(m[2].toLowerCase());
      if (id == null || !index.ids.has(id)) continue;
      frag.append(src.slice(last, m.index));
      const b = doc.createElement("button");
      b.type = "button"; b.className = REF_CLASS; b.dataset.ref = String(id); b.title = `Open overlap #${id} on the map`;
      b.innerHTML = PIN; b.append(m[0]);
      frag.append(b);
      last = m.index + m[0].length;
    }
    frag.append(src.slice(last));
    t.replaceWith(frag);
  }
  return root.innerHTML;
}

