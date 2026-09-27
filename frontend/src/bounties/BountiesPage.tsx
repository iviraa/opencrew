// /bounties: public damage-verification bounties paid in devnet SOL. Reached only by URL; the main app never links here.
import { ArrowLeft, Clock, ExternalLink, MapPin, Plus, ShieldCheck, TriangleAlert, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { bounties, type Bounty, type Tx } from "./api";
import { PostBounty, RefundButton, ReviewPanel, SubmitEvidence } from "./forms";
import { explorerAddress, explorerTx, Providers, short, WalletButton } from "./solana";

export default function BountiesPage() {
  return (
    <Providers>
      <Page />
    </Providers>
  );
}

type View = { kind: "list" } | { kind: "detail"; id: number } | { kind: "post" };

function Page() {
  const [list, setList] = useState<Bounty[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>({ kind: "list" });

  const load = useCallback(() => {
    bounties.list().then((b) => { setList(b); setError(null); }).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="grape-bg thin-scroll h-full w-full overflow-y-auto">
      <header className="mx-auto flex max-w-[1080px] flex-wrap items-center justify-between gap-3 px-6 pt-6">
        <a href="/bounties" onClick={(e) => { e.preventDefault(); setView({ kind: "list" }); load(); }} className="flex items-baseline gap-2 text-white">
          <span className="font-logo text-3xl font-semibold tracking-tight">crewly</span>
          <span className="font-logo text-xl font-medium text-white/80">bounties</span>
        </a>
        <WalletButton />
      </header>

      <div className="mx-auto mt-4 max-w-[1080px] px-6">
        <div className="flex items-start gap-2 rounded-2xl bg-crew-soft px-4 py-2.5 text-sm text-ink">
          <TriangleAlert size={17} className="mt-0.5 shrink-0 text-warn" />
          <span><b>Solana devnet only.</b> Rewards are test SOL with no real value. Set your wallet to devnet, and use a devnet-only wallet. Get free test SOL at{" "}
            <a href="https://faucet.solana.com" target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2">faucet.solana.com</a>.</span>
        </div>
      </div>

      <main className="mx-auto max-w-[1080px] px-6 pb-16 pt-8">
        <div className="board p-6 md:p-8">
          <div className="board-frame" />
          <div className="relative">
            {view.kind === "list" && (
              <BountyList list={list} error={error} onOpen={(id) => setView({ kind: "detail", id })} onPost={() => setView({ kind: "post" })} />
            )}
            {view.kind === "post" && (
              <>
                <Back onClick={() => setView({ kind: "list" })} />
                <PostBounty onPosted={(b) => { load(); setView({ kind: "detail", id: b.id }); }} />
              </>
            )}
            {view.kind === "detail" && (
              <>
                <Back onClick={() => { setView({ kind: "list" }); load(); }} />
                <BountyDetail id={view.id} />
              </>
            )}
          </div>
        </div>
        <p className="mt-6 text-center text-xs text-white/70">
          Evidence stays private with Crewly. Only its SHA-256 fingerprint, the reviewer approvals, and the payout go on-chain.
        </p>
      </main>
    </div>
  );
}

function Back({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="mb-4 flex items-center gap-1.5 text-sm font-semibold text-muted hover:text-ink">
      <ArrowLeft size={16} /> All bounties
    </button>
  );
}

export function StatusChip({ b }: { b: Bounty }) {
  const [label, cls] =
    b.status === "paid" ? ["Paid", "bg-save-soft text-save"]
    : b.status === "refunded" ? ["Refunded", "bg-soft text-muted"]
    : b.expired ? ["Expired", "bg-warn-soft text-warn"]
    : b.status === "funded" ? ["Open", "bg-desc-soft text-desc"]
    : ["Not funded", "bg-soft text-muted"];
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wide ${cls}`}>{label}</span>;
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function BountyList({ list, error, onOpen, onPost }: { list: Bounty[] | null; error: string | null; onOpen: (id: number) => void; onPost: () => void }) {
  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Damage-verification bounties</h1>
          <p className="mt-1 max-w-[620px] text-muted">
            Sponsors post a reward for verified storm-damage evidence in a broad area. People on the ground submit photos or reports, reviewers check them, and the escrowed reward pays out on Solana.
          </p>
        </div>
        <button onClick={onPost} className="pen-btn flex items-center gap-2 bg-grape px-5 py-2.5 font-logo text-lg font-semibold text-white">
          <Plus size={18} /> Post a bounty
        </button>
      </div>

      {error && <p className="mt-6 text-sm font-medium text-warn" role="alert">Could not load bounties: {error}</p>}
      {!list && !error && <p className="mt-6 text-muted"><span className="dots">Loading</span></p>}
      {list?.length === 0 && (
        <div className="mt-8 rounded-2xl border-2 border-dashed border-line p-8 text-center text-muted">
          No bounties yet. Post the first one.
        </div>
      )}

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {list?.map((b) => (
          <button key={b.id} onClick={() => onOpen(b.id)}
            className="pen-box pop-in flex flex-col gap-2 bg-white p-5 text-left transition hover:bg-grape-soft/40">
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-lg font-semibold leading-snug">{b.title}</h2>
              <StatusChip b={b} />
            </div>
            <div className="display text-2xl font-semibold text-grape">{b.reward_sol} <span className="text-base text-muted">devnet SOL</span></div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
              <span className="flex items-center gap-1"><MapPin size={14} />{b.region}</span>
              <span className="flex items-center gap-1"><Clock size={14} />{b.status === "funded" && !b.expired ? "Closes " : "Closed "}{when(b.deadline)}</span>
              <span className="flex items-center gap-1"><Users size={14} />{b.submissions} submission{b.submissions === 1 ? "" : "s"}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function BountyDetail({ id }: { id: number }) {
  const [b, setB] = useState<Bounty | null>(null);
  const [txs, setTxs] = useState<Tx[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    bounties.get(id).then(setB).catch((e) => setError(e.message));
    bounties.transactions(id).then(setTxs).catch(() => {});
  }, [id]);
  useEffect(load, [load]);
  const update = (next: Bounty) => { setB(next); bounties.transactions(id).then(setTxs).catch(() => {}); };

  if (error) return <p className="text-warn" role="alert">{error}</p>;
  if (!b) return <p className="text-muted"><span className="dots">Loading</span></p>;
  const open = b.status === "funded" && !b.expired;

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
      <div className="flex flex-col gap-6">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-semibold">{b.title}</h1>
            <StatusChip b={b} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
            <span className="flex items-center gap-1"><MapPin size={14} />{b.region}</span>
            <span className="flex items-center gap-1"><Clock size={14} />Deadline {when(b.deadline)}</span>
          </div>
          <p className="mt-4 whitespace-pre-line leading-relaxed">{b.description}</p>
        </div>

        <section>
          <h2 className="text-lg font-semibold">What counts as evidence</h2>
          <p className="mt-1 whitespace-pre-line leading-relaxed text-muted">{b.rules}</p>
        </section>

        {open && <SubmitEvidence bounty={b} onSubmitted={load} />}
        {b.status === "paid" && b.contributor && (
          <div className="rounded-2xl bg-save-soft p-5">
            <div className="flex items-center gap-2 font-semibold text-save"><ShieldCheck size={18} /> Verified and paid</div>
            <p className="mt-1 text-sm">
              {b.reward_sol} devnet SOL was released to{" "}
              <a href={explorerAddress(b.contributor)} target="_blank" rel="noreferrer" className="font-mono font-semibold underline">{short(b.contributor)}</a>{" "}
              after {b.approved_by.length} of {b.reviewers.length} reviewers approved the same evidence.
            </p>
          </div>
        )}
        <ReviewPanel bounty={b} onChange={update} />
        <RefundButton bounty={b} onChange={update} />
      </div>

      <aside className="flex flex-col gap-4">
        <div className="pen-box bg-white p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-faint">Reward in escrow</div>
          <div className="display mt-1 text-4xl font-semibold text-grape">{b.reward_sol}<span className="ml-1.5 text-lg text-muted">SOL</span></div>
          <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <dt className="text-muted">Approvals</dt>
            <dd className="font-semibold">{b.approved_by.length} of {b.threshold} needed <span className="font-normal text-muted">({b.reviewers.length} reviewer{b.reviewers.length === 1 ? "" : "s"})</span></dd>
            <dt className="text-muted">Sponsor</dt>
            <dd><Addr a={b.sponsor} /></dd>
            <dt className="text-muted">Reviewers</dt>
            <dd className="flex flex-col gap-0.5">{b.reviewers.map((r) => (
              <span key={r} className="flex items-center gap-1.5"><Addr a={r} />{b.approved_by.includes(r) && <ShieldCheck size={14} className="text-save" />}</span>
            ))}</dd>
            {b.pda && <><dt className="text-muted">Escrow</dt><dd><Addr a={b.pda} /></dd></>}
            {b.submission_commitment && <><dt className="text-muted">Evidence hash</dt><dd className="break-all font-mono text-xs">{b.submission_commitment}</dd></>}
          </dl>
        </div>

        <div className="pen-box bg-white p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-faint">On-chain activity</div>
          {txs.length === 0 && <p className="mt-2 text-sm text-muted">No transactions yet.</p>}
          <ul className="mt-2 flex flex-col gap-2">
            {txs.map((t) => (
              <li key={t.signature}>
                <a href={explorerTx(t.signature)} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-2 text-sm hover:text-grape">
                  <span className="font-semibold capitalize">{t.kind === "create" ? "Created and funded" : t.kind === "approve" ? "Reviewer approval" : "Refunded"}</span>
                  <span className="flex items-center gap-1 font-mono text-xs text-muted">{short(t.signature)}<ExternalLink size={12} /></span>
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-faint">Links open Solana Explorer on devnet.</p>
        </div>
      </aside>
    </div>
  );
}

function Addr({ a }: { a: string }) {
  return (
    <a href={explorerAddress(a)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-xs font-semibold hover:text-grape">
      {short(a)}<ExternalLink size={11} />
    </a>
  );
}
