// the four things a visitor can do: post (sponsor), submit (contributor), review and approve (reviewer), refund (sponsor)
import { getBase58Decoder } from "@solana/kit";
import { useSignMessage } from "@solana/kit-plugin-wallet/react";
import { CheckCircle2, FileText, Send, ShieldCheck, Undo2 } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { bounties, reviewMessage, type Bounty, type ReviewAuth, type Submission } from "./api";
import { approveInstruction, bountyAddress, createAndFundInstructions, refundInstruction } from "./program";
import { client, explain, explorerTx, short, useWallet } from "./solana";

const input = "pen-box w-full bg-white px-4 py-2.5 outline-none placeholder:text-faint focus:bg-grape-soft/40";

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-sm font-semibold">{label}</span>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  );
}

function Note({ kind, children }: { kind: "error" | "ok" | "info"; children: ReactNode }) {
  const cls = kind === "error" ? "text-warn" : kind === "ok" ? "text-save" : "text-muted";
  return <p className={`pop-in text-sm font-medium ${cls}`} role={kind === "error" ? "alert" : "status"}>{children}</p>;
}

async function send(instructions: Parameters<typeof client.sendTransaction>[0]) {
  const result = await client.sendTransaction(instructions);
  return result.context.signature as string;
}

const inDays = (d: number) => {
  const t = new Date(Date.now() + d * 86_400_000);
  t.setSeconds(0, 0);
  return new Date(t.getTime() - t.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);  // datetime-local wants local time
};

export function PostBounty({ onPosted }: { onPosted: (b: Bounty) => void }) {
  const wallet = useWallet();
  const [f, setF] = useState({ title: "", description: "", region: "", rules: "", reward: "0.1", deadline: inDays(7), reviewers: "", threshold: 1 });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: k === "threshold" ? Number(e.target.value) : e.target.value });

  const reviewers = (f.reviewers.trim() ? f.reviewers.split(/[\s,]+/).filter(Boolean) : wallet ? [wallet] : []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!wallet) return;
    setError(null);
    try {
      setBusy("Saving the bounty details…");
      const draft = await bounties.create({
        title: f.title.trim(), description: f.description.trim(), region: f.region.trim(), rules: f.rules.trim(),
        reward_sol: Number(f.reward), deadline: new Date(f.deadline).toISOString(), sponsor: wallet, reviewers, threshold: f.threshold,
      });
      setBusy("Approve the transaction in your wallet to create and fund the escrow…");
      const sig = await send(await createAndFundInstructions(client.identity, draft.chain_args));
      setBusy("Confirming on devnet…");
      const pda = await bountyAddress(wallet, draft.id);
      onPosted(await bounties.sync(draft.id, sig, "create", pda));
    } catch (err) {
      setError(explain(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <form onSubmit={submit} className="flex max-w-[680px] flex-col gap-4">
      <div>
        <h1 className="text-3xl font-semibold">Post a bounty</h1>
        <p className="mt-1 text-muted">Your wallet creates the bounty and moves the reward into an on-chain escrow in one transaction. Only reviewers can release it.</p>
      </div>
      {!wallet && <Note kind="info">Connect a devnet wallet (top right) to post a bounty.</Note>}
      <Field label="Title"><input className={input} value={f.title} onChange={set("title")} required minLength={3} maxLength={120} placeholder="Downed line photos after the storm" /></Field>
      <Field label="What you need"><textarea className={input} rows={3} value={f.description} onChange={set("description")} required minLength={10} maxLength={2000} /></Field>
      <Field label="Broad region" hint="A county or city. Never an exact address."><input className={input} value={f.region} onChange={set("region")} required minLength={2} maxLength={120} placeholder="Aiken County, SC" /></Field>
      <Field label="Evidence rules"><textarea className={input} rows={3} value={f.rules} onChange={set("rules")} required minLength={10} maxLength={2000} placeholder="Timestamped photo. No faces. Don't enter private property." /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Reward (devnet SOL)"><input className={input} type="number" min="0.001" max="100" step="0.001" value={f.reward} onChange={set("reward")} required /></Field>
        <Field label="Deadline"><input className={input} type="datetime-local" value={f.deadline} onChange={set("deadline")} required /></Field>
      </div>
      <Field label="Reviewer wallets" hint={`Up to 3, separated by commas or spaces. Leave empty to review it yourself${wallet ? ` (${short(wallet)})` : ""}.`}>
        <textarea className={`${input} font-mono text-sm`} rows={2} value={f.reviewers} onChange={set("reviewers")} />
      </Field>
      <Field label="Approvals needed to pay out">
        <select className={input} value={f.threshold} onChange={set("threshold")}>
          {[1, 2, 3].filter((n) => n <= Math.max(1, reviewers.length)).map((n) => <option key={n} value={n}>{n} of {Math.max(1, reviewers.length)}</option>)}
        </select>
      </Field>
      {error && <Note kind="error">{error}</Note>}
      {busy && <Note kind="info">{busy}</Note>}
      <button disabled={!wallet || !!busy} className="pen-btn flex items-center justify-center gap-2 self-start bg-grape px-6 py-3 font-logo text-lg font-semibold text-white">
        <Send size={18} /> {busy ? "Working…" : `Post and fund ${f.reward || 0} SOL`}
      </button>
    </form>
  );
}

export function SubmitEvidence({ bounty, onSubmitted }: { bounty: Bounty; onSubmitted: () => void }) {
  const wallet = useWallet();
  const [addr, setAddr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ commitment: string; duplicate: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    form.set("wallet", (addr || wallet || "").trim());
    if (!(form.get("file") as File | null)?.size) form.delete("file");
    setBusy(true); setError(null);
    try {
      setDone(await bounties.submit(bounty.id, form));
      onSubmitted();
    } catch (err) {
      setError(explain(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="pop-in rounded-2xl bg-save-soft p-5">
        <div className="flex items-center gap-2 font-semibold text-save"><CheckCircle2 size={18} /> {done.duplicate ? "Already received" : "Evidence received"}</div>
        <p className="mt-1 text-sm">
          {done.duplicate ? "We already had this exact submission." : "Reviewers will check it."} If approved, the reward goes straight to your wallet. Your evidence fingerprint:
        </p>
        <p className="mt-2 break-all font-mono text-xs">{done.commitment}</p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="pen-box flex flex-col gap-4 bg-soft p-5">
      <div>
        <h2 className="text-lg font-semibold">Submit evidence</h2>
        <p className="text-sm text-muted">Only the reviewers see what you send. Just its fingerprint can go on-chain.</p>
      </div>
      <Field label="Your Solana wallet address" hint="The reward is paid here if your evidence is approved.">
        <input className={`${input} font-mono text-sm`} value={addr || wallet || ""} onChange={(e) => setAddr(e.target.value)} required minLength={32} maxLength={44} placeholder="Paste a devnet wallet address" />
      </Field>
      <Field label="What you saw"><textarea name="summary" className={input} rows={3} required minLength={10} maxLength={2000} /></Field>
      <Field label="Where, as exactly as you can" hint="Private to reviewers."><input name="location" className={input} maxLength={300} placeholder="Street and cross street, or coordinates" /></Field>
      <Field label="More detail (optional)"><textarea name="details" className={input} rows={2} maxLength={5000} /></Field>
      <Field label="Photo or document (optional)" hint="JPEG, PNG, WebP, HEIC, PDF or text, up to 5 MB.">
        <input name="file" type="file" accept="image/jpeg,image/png,image/webp,image/heic,application/pdf,text/plain" className="text-sm" />
      </Field>
      {error && <Note kind="error">{error}</Note>}
      <button disabled={busy} className="pen-btn flex items-center justify-center gap-2 self-start bg-grape px-5 py-2.5 font-semibold text-white">
        <Send size={16} /> {busy ? "Sending…" : "Submit evidence"}
      </button>
    </form>
  );
}

export function ReviewPanel({ bounty, onChange }: { bounty: Bounty; onChange: (b: Bounty) => void }) {
  const wallet = useWallet();
  const sign = useSignMessage(client);
  const [auth, setAuth] = useState<ReviewAuth | null>(null);
  const [subs, setSubs] = useState<Submission[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastSig, setLastSig] = useState<string | null>(null);

  if (!wallet || !bounty.reviewers.includes(wallet)) return null;
  const mine = auth?.wallet === wallet ? auth : null;
  const approvedAlready = bounty.approved_by.includes(wallet);
  const canApprove = bounty.status === "funded" && !bounty.expired && !approvedAlready;

  const unlock = async () => {
    setError(null);
    try {
      const issued = Math.floor(Date.now() / 1000);
      const bytes = await sign.dispatchAsync(new TextEncoder().encode(reviewMessage(bounty.id, wallet, issued)));
      const a = { wallet, issued, signature: getBase58Decoder().decode(bytes) };
      setSubs(await bounties.submissions(bounty.id, a));
      setAuth(a);
    } catch (err) {
      setError(explain(err));
    }
  };

  const approve = async (s: Submission) => {
    if (!bounty.pda) return;
    setBusy(s.id); setError(null);
    try {
      const sig = await send([approveInstruction(client.identity, bounty.pda, s.commitment, s.wallet)]);
      setLastSig(sig);
      onChange(await bounties.sync(bounty.id, sig, "approve"));
      if (mine) setSubs(await bounties.submissions(bounty.id, mine).catch(() => subs));
    } catch (err) {
      setError(explain(err));
    } finally {
      setBusy(null);
    }
  };

  const openFile = async (s: Submission) => {
    if (!mine) return;
    try {
      const url = URL.createObjectURL(await bounties.evidence(bounty.id, s.id, mine));
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(explain(err));
    }
  };

  return (
    <section className="pen-box flex flex-col gap-4 bg-grape-soft/40 p-5">
      <div className="flex items-center gap-2">
        <ShieldCheck size={18} className="text-grape" />
        <h2 className="text-lg font-semibold">Reviewer desk</h2>
        {approvedAlready && <span className="rounded-full bg-save-soft px-2 py-0.5 text-xs font-bold text-save">You approved</span>}
      </div>
      {!mine ? (
        <>
          <p className="text-sm text-muted">You are a reviewer for this bounty. Sign a message with your wallet to prove it and see the private submissions. Signing is free and sends nothing on-chain.</p>
          <button onClick={unlock} disabled={sign.isRunning} className="pen-btn self-start bg-white px-5 py-2 font-semibold">
            {sign.isRunning ? "Waiting for wallet…" : "Sign in to review"}
          </button>
        </>
      ) : subs?.length === 0 ? (
        <p className="text-sm text-muted">No submissions yet.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {subs?.map((s) => (
            <li key={s.id} className="rounded-2xl border-2 border-line bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                <span>From <span className="font-mono font-semibold text-ink">{short(s.wallet)}</span> · {new Date(s.created_at).toLocaleString()}</span>
                {s.approved && <span className="rounded-full bg-save-soft px-2 py-0.5 font-bold text-save">{bounty.status === "paid" ? "Paid" : "Approved"}</span>}
              </div>
              <p className="mt-2 whitespace-pre-line">{s.summary}</p>
              {s.location && <p className="mt-1 text-sm"><b>Location:</b> {s.location}</p>}
              {s.details && <p className="mt-1 whitespace-pre-line text-sm text-muted">{s.details}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {s.file_name && (
                  <button onClick={() => openFile(s)} className="flex items-center gap-1.5 rounded-full border-2 border-line px-3 py-1 text-sm font-semibold hover:border-ink">
                    <FileText size={14} /> {s.file_name}
                  </button>
                )}
                {canApprove && (!bounty.submission_commitment || s.approved) && (
                  <button onClick={() => approve(s)} disabled={busy !== null} className="pen-btn flex items-center gap-1.5 bg-save px-4 py-1.5 text-sm font-semibold text-white">
                    <CheckCircle2 size={15} /> {busy === s.id ? "Approving…" : "Approve on-chain"}
                  </button>
                )}
              </div>
              <p className="mt-2 break-all font-mono text-[11px] text-faint">{s.commitment}</p>
            </li>
          ))}
        </ul>
      )}
      {lastSig && <Note kind="ok">Approval confirmed. <a className="underline" href={explorerTx(lastSig)} target="_blank" rel="noreferrer">View on Explorer</a></Note>}
      {error && <Note kind="error">{error}</Note>}
    </section>
  );
}

export function RefundButton({ bounty, onChange }: { bounty: Bounty; onChange: (b: Bounty) => void }) {
  const wallet = useWallet();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (wallet !== bounty.sponsor || bounty.status !== "funded" || !bounty.expired || !bounty.pda) return null;

  const refund = async () => {
    setBusy(true); setError(null);
    try {
      const sig = await send([refundInstruction(client.identity, bounty.pda!)]);
      onChange(await bounties.sync(bounty.id, sig, "refund"));
    } catch (err) {
      setError(explain(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="pen-box flex flex-col gap-3 bg-warn-soft p-5">
      <h2 className="text-lg font-semibold">This bounty expired unpaid</h2>
      <p className="text-sm">As the sponsor, you can take the {bounty.reward_sol} SOL back out of escrow.</p>
      {error && <Note kind="error">{error}</Note>}
      <button onClick={refund} disabled={busy} className="pen-btn flex items-center gap-2 self-start bg-white px-5 py-2 font-semibold">
        <Undo2 size={16} /> {busy ? "Refunding…" : "Refund to my wallet"}
      </button>
    </section>
  );
}
