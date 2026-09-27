// the four things a visitor can do: post (sponsor), submit (contributor), review and approve (reviewer), refund (sponsor)
import { getBase58Decoder } from "@solana/kit";
import { useSignMessage } from "@solana/kit-plugin-wallet/react";
import { CheckCircle2, FileText, Flag, Send, ShieldCheck, Undo2 } from "lucide-react";
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

const claimedKey = (id: number) => `crewly-bounty-claimed-${id}`;
const readClaim = (id: number) => { try { return localStorage.getItem(claimedKey(id)); } catch { return null; } };
const writeClaim = (id: number, v: string) => { try { localStorage.setItem(claimedKey(id), v); } catch { /* private mode: state lives for this visit only */ } };

export function ClaimBounty({ bounty, onSubmitted }: { bounty: Bounty; onSubmitted: () => void }) {
  const wallet = useWallet();
  const [stage, setStage] = useState<"open" | "claimed" | "submitted">(() => (readClaim(bounty.id) as "claimed" | "submitted" | null) ?? "open");
  const [addr, setAddr] = useState("");
  const [email, setEmail] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const address = (addr || wallet || "").trim();

  const claim = () => { setStage("claimed"); writeClaim(bounty.id, "claimed"); };

  const review = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setConfirming(true);
  };

  const confirm = async () => {
    const form = new FormData();
    form.set("wallet", address);
    form.set("email", email.trim());
    setBusy(true); setError(null);
    try {
      await bounties.submit(bounty.id, form);
      setConfirming(false);
      setStage("submitted"); writeClaim(bounty.id, "submitted");
      onSubmitted();
    } catch (err) {
      setConfirming(false);
      setError(explain(err));
    } finally {
      setBusy(false);
    }
  };

  if (stage === "submitted") {
    return (
      <div className="pop-in rounded-2xl bg-save-soft p-5">
        <div className="flex items-center gap-2 text-lg font-semibold text-save"><CheckCircle2 size={20} /> Submitted</div>
        <p className="mt-1">You will receive updates by email. If your claim is approved, the {bounty.reward_sol} SOL reward is paid on-chain to your Solana address.</p>
      </div>
    );
  }

  return (
    <section className="pen-box flex flex-col gap-4 bg-soft p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Claim this bounty</h2>
          <p className="text-sm text-muted">Claim it, then tell us where to send the reward and how to reach you.</p>
        </div>
        <button onClick={claim} disabled={stage !== "open"}
          className="pen-btn flex items-center gap-2 bg-grape px-5 py-2.5 font-logo text-lg font-semibold text-white">
          <Flag size={17} /> {stage === "open" ? "Claim" : "Claimed"}
        </button>
      </div>

      <form onSubmit={review} className={`flex flex-col gap-4 ${stage === "open" ? "pointer-events-none opacity-50" : "pop-in"}`} aria-disabled={stage === "open"}>
        <Field label="Your Solana address" hint="The reward is paid here.">
          <input className={`${input} font-mono text-sm`} value={address} onChange={(e) => setAddr(e.target.value)} disabled={stage === "open"}
            required minLength={32} maxLength={44} pattern="[1-9A-HJ-NP-Za-km-z]{32,44}" title="A Solana address (base58, 32 to 44 characters)" placeholder="Paste your Solana address" />
        </Field>
        <Field label="Email" hint="We send status updates here.">
          <input className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} disabled={stage === "open"}
            required maxLength={254} placeholder="you@example.com" autoComplete="email" />
        </Field>
        {error && <Note kind="error">{error}</Note>}
        <button disabled={stage === "open"} className="pen-btn flex items-center justify-center gap-2 self-start bg-grape px-5 py-2.5 font-semibold text-white">
          <Send size={16} /> Submit
        </button>
      </form>

      {confirming && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4" role="dialog" aria-modal="true" aria-labelledby="confirm-title"
          onClick={() => !busy && setConfirming(false)}>
          <div className="board pop-in w-full max-w-[460px] p-6" onClick={(e) => e.stopPropagation()}>
            <h2 id="confirm-title" className="text-xl font-semibold">Confirm your details</h2>
            <p className="mt-1 text-sm text-muted">Check these carefully. Rewards sent to a wrong address cannot be recovered.</p>
            <dl className="mt-4 flex flex-col gap-3">
              <div><dt className="text-xs font-semibold uppercase tracking-wider text-faint">Email</dt><dd className="break-all font-semibold">{email.trim()}</dd></div>
              <div><dt className="text-xs font-semibold uppercase tracking-wider text-faint">Solana address</dt><dd className="break-all font-mono text-sm font-semibold">{address}</dd></div>
            </dl>
            <div className="mt-6 flex justify-end gap-3">
              <button onClick={() => setConfirming(false)} disabled={busy} className="rounded-full border-2 border-line px-5 py-2 font-semibold hover:border-ink">Edit</button>
              <button onClick={confirm} disabled={busy} className="pen-btn bg-grape px-5 py-2 font-semibold text-white">{busy ? "Submitting…" : "Confirm and submit"}</button>
            </div>
          </div>
        </div>
      )}
    </section>
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
              {s.email && <p className="mt-2"><b>Email:</b> <a className="underline" href={`mailto:${s.email}`}>{s.email}</a></p>}
              {s.summary && <p className="mt-2 whitespace-pre-line">{s.summary}</p>}
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
