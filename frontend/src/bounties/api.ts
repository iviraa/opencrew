// /api/bounties: public records, evidence upload, and the reviewer-only submission list
import { API_BASE } from "../apiBase";

export type Status = "created" | "funded" | "paid" | "refunded";

export type Bounty = {
  id: number; title: string; description: string; region: string; rules: string;
  reward_lamports: number; reward_sol: number; deadline: string; sponsor: string; reviewers: string[]; threshold: number;
  rules_commitment: string; region_commitment: string; pda: string | null; status: Status; approved_by: string[];
  contributor: string | null; submission_commitment: string | null; funded_at: string | null; settled_at: string | null;
  created_at: string; expired: boolean; submissions: number; explorer: string | null;
};

export type ChainArgs = {
  bounty_id: number; reward_lamports: number; deadline: number; rules_commitment: string; region_commitment: string;
  reviewers: string[]; threshold: number;
};

export type Tx = { signature: string; kind: "create" | "approve" | "refund"; created_at: string; explorer: string };

export type Submission = {
  id: number; wallet: string; email: string | null; summary: string; details: string | null; location: string | null; file_name: string | null;
  file_type: string | null; file_sha256: string | null; commitment: string; created_at: string; approved: boolean;
};

export type ReviewAuth = { wallet: string; issued: number; signature: string };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + "/api/bounties" + path, init);
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  return res.json();
}

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const auth = (a: ReviewAuth) => ({ "X-Bounty-Wallet": a.wallet, "X-Bounty-Issued": String(a.issued), "X-Bounty-Signature": a.signature });

export const bounties = {
  config: () => req<{ cluster: string; rpc_url: string; program_id: string; ready: boolean }>("/config"),
  list: () => req<Bounty[]>(""),
  get: (id: number) => req<Bounty>(`/${id}`),
  transactions: (id: number) => req<Tx[]>(`/${id}/transactions`),
  create: (body: { title: string; description: string; region: string; rules: string; reward_sol: number; deadline: string;
    sponsor: string; reviewers: string[]; threshold: number }) => req<{ id: number; chain_args: ChainArgs }>("", json(body)),
  sync: (id: number, signature: string, kind: Tx["kind"], pda?: string) => req<Bounty>(`/${id}/sync`, json({ signature, kind, pda })),
  submit: (id: number, form: FormData) => req<{ id: number; commitment: string; duplicate: boolean }>(`/${id}/submissions`, { method: "POST", body: form }),
  submissions: (id: number, a: ReviewAuth) => req<Submission[]>(`/${id}/submissions`, { headers: auth(a) }),
  evidence: async (id: number, sid: number, a: ReviewAuth) => {
    const res = await fetch(`${API_BASE}/api/bounties/${id}/submissions/${sid}/evidence`, { headers: auth(a) });
    if (!res.ok) throw new Error("could not load the evidence file");
    return res.blob();
  },
};

// must match review_message() in backend/app/bounties/api.py
export const reviewMessage = (id: number, wallet: string, issued: number) =>
  `Crewly bounty review access. bounty=${id} wallet=${wallet} issued=${issued}`;
