// instructions for the crewly_bounty program, built with the Codama client in ./generated (regenerate: see solana/README.md)
import { address, type Instruction, type TransactionSigner } from "@solana/kit";
import type { ChainArgs } from "./api";
import {
  findBountyPda,
  getApproveSubmissionInstruction,
  getCreateBountyInstructionAsync,
  getFundBountyInstruction,
  getRefundExpiredInstruction,
} from "./generated";

const hex32 = (hex: string) => {
  if (!/^[0-9a-f]{64}$/i.test(hex)) throw new Error("expected a 32-byte hex commitment");
  return Uint8Array.from(hex.match(/../g)!, (b) => parseInt(b, 16));
};

export async function bountyAddress(sponsor: string, bountyId: number) {
  const [pda] = await findBountyPda({ sponsor: address(sponsor), bountyId });
  return pda as string;
}

/** create_bounty + fund_bounty in one transaction, so a bounty never sits on-chain unfunded. */
export async function createAndFundInstructions(sponsor: TransactionSigner, a: ChainArgs): Promise<Instruction[]> {
  const create = await getCreateBountyInstructionAsync({
    sponsor,
    bountyId: a.bounty_id,
    rewardLamports: a.reward_lamports,
    deadline: a.deadline,
    rulesCommitment: hex32(a.rules_commitment),
    regionCommitment: hex32(a.region_commitment),
    reviewers: a.reviewers.map((r) => address(r)),
    threshold: a.threshold,
  });
  const bounty = address(await bountyAddress(sponsor.address, a.bounty_id));
  return [create, getFundBountyInstruction({ sponsor, bounty })];
}

export function approveInstruction(reviewer: TransactionSigner, bounty: string, commitmentHex: string, contributor: string): Instruction {
  return getApproveSubmissionInstruction({
    reviewer,
    bounty: address(bounty),
    contributor: address(contributor),
    submissionCommitment: hex32(commitmentHex),
    contributorArg: address(contributor),
  });
}

export function refundInstruction(sponsor: TransactionSigner, bounty: string): Instruction {
  return getRefundExpiredInstruction({ sponsor, bounty: address(bounty) });
}
