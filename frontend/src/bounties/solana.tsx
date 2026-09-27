// the one Kit client for the bounty page: devnet RPC plus whichever Wallet Standard wallet the visitor connects
import { createClient } from "@solana/kit";
import { solanaRpc } from "@solana/kit-plugin-rpc";
import { walletSigner } from "@solana/kit-plugin-wallet";
import { useConnect, useConnectedWallet, useDisconnect, useWallets, WalletReadyGate } from "@solana/kit-plugin-wallet/react";
import { ClientProvider } from "@solana/react";
import { LogOut, Wallet } from "lucide-react";
import type { ReactNode } from "react";

export const RPC_URL = "https://api.devnet.solana.com";  // devnet only, by design

// version 0: our transactions are a few hundred bytes, and every current wallet signs v0 (not all sign v1 yet)
export const client = createClient()
  .use(walletSigner({ chain: "solana:devnet" }))
  .use(solanaRpc({ rpcUrl: RPC_URL, transactionConfig: { version: 0 } }));

export type AppClient = typeof client;

export function Providers({ children }: { children: ReactNode }) {
  return <ClientProvider client={client}>{children}</ClientProvider>;
}

export const explorerTx = (sig: string) => `https://explorer.solana.com/tx/${sig}?cluster=devnet`;
export const explorerAddress = (a: string) => `https://explorer.solana.com/address/${a}?cluster=devnet`;
export const short = (a: string) => `${a.slice(0, 4)}…${a.slice(-4)}`;

export function useWallet() {
  return useConnectedWallet(client)?.account.address ?? null;
}

function WalletPicker() {
  const wallets = useWallets(client);
  const connected = useConnectedWallet(client);
  const connect = useConnect(client);
  const disconnect = useDisconnect(client);

  if (connected) {
    return (
      <div className="flex items-center gap-2">
        <a href={explorerAddress(connected.account.address)} target="_blank" rel="noreferrer"
          className="flex items-center gap-2 rounded-full border-2 border-line bg-white px-3 py-1.5 text-sm font-semibold hover:border-ink">
          <span className="h-2.5 w-2.5 rounded-full bg-save" />{short(connected.account.address)}
        </a>
        <button onClick={() => disconnect.dispatch()} title="Disconnect wallet" aria-label="Disconnect wallet"
          className="grid h-9 w-9 place-items-center rounded-full border-2 border-line bg-white text-muted hover:border-ink hover:text-ink">
          <LogOut size={16} />
        </button>
      </div>
    );
  }
  if (!wallets.length) {
    return (
      <a href="https://phantom.com/download" target="_blank" rel="noreferrer" className="text-sm font-semibold text-white/90 underline underline-offset-2">
        Install a Solana wallet to connect
      </a>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      {wallets.map((w) => (
        <button key={w.name} onClick={() => connect.dispatch(w)} disabled={connect.isRunning}
          className="pen-btn flex items-center gap-2 bg-white px-4 py-1.5 text-sm font-semibold text-ink">
          {w.icon ? <img src={w.icon} alt="" className="h-4 w-4" /> : <Wallet size={16} />}
          {connect.isRunning ? "Connecting…" : `Connect ${w.name}`}
        </button>
      ))}
      {connect.error ? <span className="text-sm text-white/90">Connection was cancelled.</span> : null}
    </div>
  );
}

export function WalletButton() {
  return (
    <WalletReadyGate client={client} fallback={<span className="text-sm text-white/80">Looking for wallets…</span>}>
      <WalletPicker />
    </WalletReadyGate>
  );
}

/** Turns wallet and program failures into something a person can act on. */
export function explain(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/reject|denied|cancel/i.test(msg)) return "You declined the request in your wallet.";
  if (/insufficient|0x1\b|debit an account/i.test(msg)) return "Not enough devnet SOL in this wallet. Get some free from faucet.solana.com.";
  if (/blockhash/i.test(msg)) return "The transaction took too long and expired. Please try again.";
  const custom = msg.match(/custom program error: (0x[0-9a-f]+)/i);
  if (custom) return PROGRAM_ERRORS[parseInt(custom[1], 16)] ?? msg;
  return msg;
}

// BountyError in solana/programs/crewly_bounty/src/lib.rs, numbered from Anchor's 6000
const PROGRAM_ERRORS: Record<number, string> = {
  6000: "The deadline must be in the future.",
  6001: "The reward is too small to pay out.",
  6002: "Reviewers must be 1 to 3 different wallets.",
  6003: "The approval threshold must be between 1 and the number of reviewers.",
  6004: "This bounty is already funded.",
  6005: "This bounty is not open.",
  6006: "The deadline has passed.",
  6007: "The deadline has not passed yet.",
  6008: "This wallet is not a reviewer for this bounty.",
  6009: "This wallet has already approved.",
  6010: "Another reviewer already approved a different submission.",
  6011: "The payout wallet does not match the approved contributor.",
};
