import { ExternalLink, FileText, Printer, RefreshCw } from "lucide-react";
import { useState } from "react";
import { API_BASE } from "../../apiBase";
import { api, supabase } from "../data";
import { Card, Chip, Drawer, Lead, Note, Pill, Row, StatRow, dateShort } from "../ui";
import { KIND_LABEL, SECTION_LABEL, type Report } from "./types";

const fetchHtml = async (id: number) => {
  const token = (await supabase.auth.getSession()).data.session?.access_token;
  const res = await fetch(`${API_BASE}/api/app/report/${id}`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(res.statusText);
  return res.text();
};

// a printable report crewly wrote: a document preview in the chat, opened in a new tab with the login; sections can be trimmed and regenerated
export default function ReportCard({ report: initial }: { report: Report }) {
  const [report, setReport] = useState(initial);
  const [picked, setPicked] = useState<string[]>(initial.sections);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const open = async (print = false) => {
    setErr(null);
    const win = window.open("", "_blank");  // open first so browsers allow it, then fill it
    try {
      const html = await fetchHtml(report.id);
      if (!win) throw new Error("The browser blocked the new tab.");
      win.document.open(); win.document.write(html); win.document.close();
      if (print) setTimeout(() => win.print(), 400);
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
  const kind = KIND_LABEL[report.kind] ?? report.kind.replace(/_/g, " ");
  const figures = (report.figures ?? []).slice(0, 4);

  return (
    <Card icon={<FileText size={15} />} title={report.title} busy={busy}
      sub={<Row><Chip tone="info">{kind}</Chip><span>{dateShort(report.created_at)}</span><span>· {report.sections.length} section{report.sections.length === 1 ? "" : "s"}</span></Row>}>
      <Lead>{report.summary ?? `A printable ${kind.toLowerCase()} covering ${report.sections.map((s) => (SECTION_LABEL[s] ?? s).toLowerCase()).join(", ")}.`}</Lead>
      {figures.length > 0 && <StatRow items={figures.map((f) => ({ label: f.label, value: f.value, note: f.note }))} cols={figures.length >= 4 ? 2 : undefined} />}
      <Drawer title="Sections" summary={report.all_sections.map((s) => SECTION_LABEL[s] ?? s).join(" · ")}>
        <Row>
          {report.all_sections.map((s) => (
            <label key={s} className={`flex cursor-pointer items-center gap-1 rounded-full border-2 px-2 py-0.5 text-[11px] font-semibold ${picked.includes(s) ? "border-pen" : "border-line text-muted"}`}>
              <input type="checkbox" className="hidden" checked={picked.includes(s)} onChange={(e) => setPicked((p) => e.target.checked ? [...p, s] : p.filter((x) => x !== s))} />
              {SECTION_LABEL[s] ?? s}
            </label>
          ))}
        </Row>
        {changed ? <Pill onClick={regenerate} disabled={busy || !picked.length} icon={<RefreshCw size={12} />}>{busy ? "Writing" : "Rewrite with these sections"}</Pill>
          : <Note>Untick a section and rewrite to get a shorter document.</Note>}
      </Drawer>
      <Row>
        <Pill primary grow onClick={() => open(false)} icon={<ExternalLink size={13} />}>Open report</Pill>
        <Pill onClick={() => open(true)} icon={<Printer size={13} />}>Print / PDF</Pill>
      </Row>
      {err && <Note tone="warn">{err}</Note>}
    </Card>
  );
}
