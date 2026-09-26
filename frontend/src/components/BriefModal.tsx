import { marked } from "marked";

export default function BriefModal({ markdown, source, onClose }: { markdown: string; source: string; onClose: () => void }) {
  const html = marked.parse(markdown) as string;

  const download = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([markdown], { type: "text/markdown" }));
    a.download = "coordination-brief.md";
    a.click();
  };

  const print = () => {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`<html><head><title>Coordination brief</title><style>body{font:14px system-ui;max-width:800px;margin:40px auto;color:#0f172a}
      table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #cbd5e1;padding:4px 6px;text-align:left}</style></head><body>${html}</body></html>`);
    w.document.close();
    w.print();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-6" onClick={onClose}>
      <div className="flex max-h-full w-[860px] flex-col rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3">
          <div className="text-sm font-semibold">Coordination brief <span className="ml-2 text-xs font-normal text-slate-500">summary by {source}</span></div>
          <div className="flex gap-2">
            <button onClick={download} className="rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200">Download .md</button>
            <button onClick={print} className="rounded-md bg-slate-100 px-3 py-1.5 text-xs font-medium hover:bg-slate-200">Print / PDF</button>
            <button onClick={onClose} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
          </div>
        </div>
        <article className="brief overflow-y-auto px-6 py-5 text-sm" dangerouslySetInnerHTML={{ __html: html }} />
      </div>
    </div>
  );
}
