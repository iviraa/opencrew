import { FileUp } from "lucide-react";
import { useState } from "react";
import { api, type IngestResult } from "../api";
import { Button } from "./ui";
import { Field, Modal, inputClass } from "./ui-extra";

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
    <Modal title="Add a utility filing" onClose={onClose}
      subtitle="Drop in a public planning PDF. OpenCrew reads the projects, places them on the map and finds new overlaps.">
      <div className="space-y-4 pt-2">
        <label className="flex cursor-pointer flex-col items-center gap-2 rounded-[20px] border-2 border-dashed border-line bg-soft px-4 py-6 text-center hover:border-desc">
          <FileUp size={26} className="text-desc" />
          <span className="text-[15px] font-semibold">{file ? file.name : "Choose a PDF"}</span>
          <span className="text-[13px] text-muted">Documents marked CEII are refused</span>
          <input type="file" accept="application/pdf" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <Field label="Or paste a link to the PDF">
          <input value={url} onChange={(e) => setUrl(e.target.value)} disabled={!!file} placeholder="https://" className={inputClass} />
        </Field>
        <details className="rounded-[20px] bg-soft px-4 py-3">
          <summary className="cursor-pointer text-[14px] font-semibold">A utility OpenCrew hasn't seen before</summary>
          <p className="mt-1 text-[13px] text-muted">Only needed when the layout isn't recognized. Gemini reads it and every row is checked.</p>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <input value={org} onChange={(e) => setOrg(e.target.value)} placeholder="Short id" aria-label="Utility id" className={inputClass} />
            <input value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Full name" aria-label="Utility name" className={inputClass} />
            <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Home state" className={inputClass}>
              {["SC", "GA", "NC", "FL", "AL", "TN", "VA"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </details>
        {error && <div className="rounded-2xl bg-warn-soft px-4 py-3 text-[14px] text-warn">{error}</div>}
        {result && (
          <div className="rounded-2xl bg-save-soft px-4 py-3 text-[14px]">
            <div className="display text-[18px] font-semibold text-save">Added {result.rows} projects</div>
            <p className="mt-1 text-ink/80">
              Read {result.pages} pages in {result.seconds} seconds. {result.placed ?? 0} are on the map and {result.unplaced ?? 0} need a location.
              {result.ceii_page ? ` ${result.ceii_page} projects on CEII pages were skipped.` : ""} There are now {result.long.pairs} long-range and {result.near.pairs} near-term opportunities.
            </p>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" onClick={onClose}>{result ? "Done" : "Cancel"}</Button>
          <Button variant="primary" onClick={submit} disabled={busy || (!file && !url.trim())}>{busy ? "Reading the filing…" : "Add filing"}</Button>
        </div>
      </div>
    </Modal>
  );
}
