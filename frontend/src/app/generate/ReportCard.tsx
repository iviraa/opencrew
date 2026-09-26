import { ExternalLink, FileText, RefreshCw } from "lucide-react";
import { useState } from "react";
import { API_BASE } from "../../apiBase";
import { api, supabase } from "../data";
import { SECTION_LABEL, type Report } from "./types";

// a printable report crewly wrote: opens in a new tab (fetched with the login, shown from a blob), sections can be trimmed and regenerated
export default function ReportCard({ report: initial }: { report: Report }) {
  const [report, setReport] = useState(initial);
  const [picked, setPicked] = useState<string[]>(initial.sections);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const open = async () => {
    setErr(null);
    const win = window.open("", "_blank");  // open first so browsers allow it, then fill it
    try {
      const token = (await supabase.auth.getSession()).data.session?.access_token;
      const res = await fetch(`${API_BASE}/api/app/report/${report.id}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(res.statusText);
      const url = URL.createObjectURL(await res.blob());
      if (win) win.location.href = url; else window.location.href = url;
    } catch (e) { win?.close(); setErr(e instanceof Error ? e.message : String(e)); }
  };

  const regenerate = async () => {
    setBusy(true); setErr(null);
    try {
      setReport(await api.send<Report>("/api/app/report", "POST", { kind: report.kind, id: report.ref_id, sections: picked }));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const changed = picked.join() !== report.sections.join();

  return (
    <div className="pop-in rounded-2xl border-2 border-pen bg-white p-2">
      <div className="flex items-start gap-2 px-1">
        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-grape-soft text-grape"><FileText size={16} /></span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-snug">{report.title}</div>
          <div className="text-[11px] text-faint">Print or save as PDF from the page</div>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1 px-1">
        {report.all_sections.map((s) => (
          <label key={s} className={`flex cursor-pointer items-center gap-1 rounded-full border-2 px-2 py-0.5 text-[11px] font-semibold ${picked.includes(s) ? "border-pen" : "border-line text-muted"}`}>
            <input type="checkbox" className="hidden" checked={picked.includes(s)} onChange={(e) => setPicked((p) => e.target.checked ? [...p, s] : p.filter((x) => x !== s))} />
            {SECTION_LABEL[s] ?? s}
          </label>
        ))}
      </div>
      <div className="mt-2 flex gap-1.5 px-1">
        <button onClick={open} className="flex flex-1 items-center justify-center gap-1 rounded-full bg-grape px-2.5 py-1 text-xs font-semibold text-white"><ExternalLink size={13} /> Open report</button>
        {changed && <button onClick={regenerate} disabled={busy || !picked.length} className="flex items-center justify-center gap-1 rounded-full border-2 border-line px-2.5 py-1 text-xs font-semibold hover:border-pen disabled:opacity-40"><RefreshCw size={13} /> {busy ? "..." : "Regenerate"}</button>}
      </div>
      {err && <p className="px-1 pt-1 text-[11px] text-warn">{err}</p>}
    </div>
  );
}
