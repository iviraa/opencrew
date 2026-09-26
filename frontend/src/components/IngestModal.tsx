import { useState } from "react";
import { api, type IngestResult } from "../api";

export default function IngestModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [org, setOrg] = useState("");
  const [orgName, setOrgName] = useState("");
  const [state, setState] = useState("SC");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<IngestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const form = new FormData();
    if (file) form.append("file", file);
    else form.append("url", url);
    if (org.trim()) { form.append("org", org.trim().toLowerCase()); form.append("org_name", orgName.trim() || org.trim()); form.append("state", state); }
    setBusy(true); setError(null); setResult(null);
    api.ingest(form).then((r) => { setResult(r); onDone(); }).catch((e) => setError(e instanceof Error ? e.message : String(e))).finally(() => setBusy(false));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-6" onClick={onClose}>
      <div className="w-[520px] rounded-xl bg-white p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Add a utility filing</h2>
          <button onClick={onClose} className="rounded px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Public PDFs only. Documents marked CEII are refused. Known layouts are parsed by code; other layouts go through Gemini and every row is schema-checked.
        </p>
        <div className="mt-4 space-y-3 text-sm">
          <label className="block">
            <span className="text-xs font-medium text-slate-600">PDF file</span>
            <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1 block w-full text-xs" />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">or a link to the PDF</span>
            <input value={url} onChange={(e) => setUrl(e.target.value)} disabled={!!file} placeholder="https://…"
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-xs disabled:bg-slate-50" />
          </label>
          <details className="rounded-md bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
            <summary className="cursor-pointer text-xs font-medium text-slate-600">New utility (only if the layout isn't recognised)</summary>
            <div className="mt-2 grid grid-cols-3 gap-2">
              <input value={org} onChange={(e) => setOrg(e.target.value)} placeholder="id, e.g. santee" className="rounded border border-slate-300 px-2 py-1 text-xs" />
              <input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Santee Cooper" className="rounded border border-slate-300 px-2 py-1 text-xs" />
              <select value={state} onChange={(e) => setState(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-xs">
                {["SC", "GA", "NC", "FL", "AL", "TN", "VA"].map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
          </details>
        </div>
        {error && <div className="mt-3 rounded bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
        {result && (
          <div className="mt-3 rounded bg-emerald-50 px-3 py-2 text-xs text-emerald-900 ring-1 ring-emerald-200">
            <b>{result.org.toUpperCase()}</b> via {result.method} in {result.seconds}s: {result.pages} pages, {result.rows} projects, {result.placed ?? 0} placed,{" "}
            {result.unplaced ?? 0} to review{result.ceii_page ? `, ${result.ceii_page} on CEII pages skipped` : ""}. Now {result.long.pairs} long-range and {result.near.pairs} near-term opportunities.
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium hover:bg-slate-200">Close</button>
          <button onClick={submit} disabled={busy || (!file && !url.trim())}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40">{busy ? "Ingesting…" : "Ingest"}</button>
        </div>
      </div>
    </div>
  );
}
