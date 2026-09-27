use crate::{accounts, instruction, Bounty, BountyStatus, BOUNTY_SEED, ID as PROGRAM_ID};
use anchor_lang::{system_program, AccountDeserialize, InstructionData, ToAccountMetas};
use litesvm::LiteSVM;
use solana_sdk::{
    clock::Clock,
    instruction::Instruction,
    pubkey::Pubkey,
    signature::Keypair,
    signer::Signer,
    transaction::Transaction,
};

const SOL: u64 = 1_000_000_000;
const REWARD: u64 = SOL / 2;
const DAY: i64 = 86_400;

struct Env {
    svm: LiteSVM,
    sponsor: Keypair,
    reviewers: Vec<Keypair>,
    contributor: Pubkey,
}

fn env(n_reviewers: usize) -> Env {
    let mut svm = LiteSVM::new();
    svm.add_program(
        PROGRAM_ID,
        include_bytes!("../../../target/deploy/crewly_bounty.so"),
    )
    .unwrap();
    let mut clock = svm.get_sysvar::<Clock>();
    clock.unix_timestamp = 1_800_000_000;
    svm.set_sysvar(&clock);

    let sponsor = Keypair::new();
    svm.airdrop(&sponsor.pubkey(), 10 * SOL).unwrap();
    let reviewers: Vec<Keypair> = (0..n_reviewers).map(|_| Keypair::new()).collect();
    for r in &reviewers {
        svm.airdrop(&r.pubkey(), SOL).unwrap();
    }
    // The contributor is a fresh wallet that has never held lamports.
    Env { svm, sponsor, reviewers, contributor: Pubkey::new_unique() }
}

fn now(svm: &LiteSVM) -> i64 {
    svm.get_sysvar::<Clock>().unix_timestamp
}

fn warp(svm: &mut LiteSVM, secs: i64) {
    let mut clock = svm.get_sysvar::<Clock>();
    clock.unix_timestamp += secs;
    svm.set_sysvar(&clock);
    svm.expire_blockhash();
}

fn pda(sponsor: &Pubkey, id: u64) -> Pubkey {
    Pubkey::find_program_address(&[BOUNTY_SEED, sponsor.as_ref(), &id.to_le_bytes()], &PROGRAM_ID).0
}

fn send(svm: &mut LiteSVM, ix: Instruction, payer: &Keypair) -> Result<(), String> {
    let tx = Transaction::new_signed_with_payer(&[ix], Some(&payer.pubkey()), &[payer], svm.latest_blockhash());
    let res = svm.send_transaction(tx).map(|_| ()).map_err(|e| format!("{:?}", e.meta.logs));
    svm.expire_blockhash();
    res
}

fn create_ix(e: &Env, id: u64, threshold: u8, deadline: i64) -> Instruction {
    Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::CreateBounty {
            sponsor: e.sponsor.pubkey(),
            bounty: pda(&e.sponsor.pubkey(), id),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
        data: instruction::CreateBounty {
            bounty_id: id,
            reward_lamports: REWARD,
            deadline,
            rules_commitment: [1; 32],
            region_commitment: [2; 32],
            reviewers: e.reviewers.iter().map(|k| k.pubkey()).collect(),
            threshold,
        }
        .data(),
    }
}

fn fund_ix(sponsor: &Pubkey, id: u64) -> Instruction {
    Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::FundBounty {
            sponsor: *sponsor,
            bounty: pda(sponsor, id),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
        data: instruction::FundBounty {}.data(),
    }
}

fn approve_ix(reviewer: &Pubkey, bounty: Pubkey, commitment: [u8; 32], contributor: Pubkey, account: Pubkey) -> Instruction {
    Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::ApproveSubmission { reviewer: *reviewer, bounty, contributor: account }
            .to_account_metas(None),
        data: instruction::ApproveSubmission { submission_commitment: commitment, contributor }.data(),
    }
}

fn refund_ix(sponsor: &Pubkey, id: u64) -> Instruction {
    Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::RefundExpired { sponsor: *sponsor, bounty: pda(sponsor, id) }.to_account_metas(None),
        data: instruction::RefundExpired {}.data(),
    }
}

fn state(svm: &LiteSVM, key: &Pubkey) -> Bounty {
    let acct = svm.get_account(key).unwrap();
    Bounty::try_deserialize(&mut acct.data.as_slice()).unwrap()
}

/// Creates and funds bounty `id`; returns its PDA.
fn funded(e: &mut Env, id: u64, threshold: u8) -> Pubkey {
    let deadline = now(&e.svm) + DAY;
    let ix = create_ix(e, id, threshold, deadline);
    send(&mut e.svm, ix, &e.sponsor).unwrap();
    send(&mut e.svm, fund_ix(&e.sponsor.pubkey(), id), &e.sponsor).unwrap();
    pda(&e.sponsor.pubkey(), id)
}

fn approve(e: &mut Env, who: usize, bounty: Pubkey, commitment: [u8; 32]) -> Result<(), String> {
    let r = e.reviewers[who].insecure_clone();
    let c = e.contributor;
    send(&mut e.svm, approve_ix(&r.pubkey(), bounty, commitment, c, c), &r)
}

#[test]
fn one_of_one_pays_contributor() {
    let mut e = env(1);
    let b = funded(&mut e, 1, 1);
    assert_eq!(state(&e.svm, &b).status, BountyStatus::Funded);

    approve(&mut e, 0, b, [9; 32]).unwrap();
    let s = state(&e.svm, &b);
    assert_eq!(s.status, BountyStatus::Paid);
    assert_eq!(s.contributor, e.contributor);
    assert_eq!(s.submission_commitment, [9; 32]);
    assert_eq!(e.svm.get_balance(&e.contributor).unwrap(), REWARD);
}

#[test]
fn two_of_three_pays_only_at_threshold() {
    let mut e = env(3);
    let b = funded(&mut e, 7, 2);

    approve(&mut e, 0, b, [9; 32]).unwrap();
    assert_eq!(state(&e.svm, &b).status, BountyStatus::Funded);
    assert_eq!(e.svm.get_balance(&e.contributor).unwrap_or(0), 0);

    approve(&mut e, 2, b, [9; 32]).unwrap();
    assert_eq!(state(&e.svm, &b).status, BountyStatus::Paid);
    assert_eq!(e.svm.get_balance(&e.contributor).unwrap(), REWARD);
}

#[test]
fn duplicate_approval_rejected() {
    let mut e = env(3);
    let b = funded(&mut e, 1, 2);
    approve(&mut e, 0, b, [9; 32]).unwrap();
    assert!(approve(&mut e, 0, b, [9; 32]).is_err());
    assert_eq!(state(&e.svm, &b).approvals.count_ones(), 1);
}

#[test]
fn mismatched_commitment_rejected() {
    let mut e = env(3);
    let b = funded(&mut e, 1, 2);
    approve(&mut e, 0, b, [9; 32]).unwrap();
    assert!(approve(&mut e, 1, b, [8; 32]).is_err());
    assert_eq!(state(&e.svm, &b).status, BountyStatus::Funded);
}

#[test]
fn mismatched_contributor_rejected() {
    let mut e = env(3);
    let b = funded(&mut e, 1, 2);
    approve(&mut e, 0, b, [9; 32]).unwrap();
    let other = Pubkey::new_unique();
    let r = e.reviewers[1].insecure_clone();
    assert!(send(&mut e.svm, approve_ix(&r.pubkey(), b, [9; 32], other, other), &r).is_err());
}

#[test]
fn contributor_account_must_match_argument() {
    let mut e = env(1);
    let b = funded(&mut e, 1, 1);
    let thief = Pubkey::new_unique();
    let r = e.reviewers[0].insecure_clone();
    let c = e.contributor;
    assert!(send(&mut e.svm, approve_ix(&r.pubkey(), b, [9; 32], c, thief), &r).is_err());
    assert_eq!(e.svm.get_balance(&thief).unwrap_or(0), 0);
}

#[test]
fn non_reviewer_rejected() {
    let mut e = env(1);
    let b = funded(&mut e, 1, 1);
    let outsider = Keypair::new();
    e.svm.airdrop(&outsider.pubkey(), SOL).unwrap();
    let c = e.contributor;
    assert!(send(&mut e.svm, approve_ix(&outsider.pubkey(), b, [9; 32], c, c), &outsider).is_err());
}

#[test]
fn no_second_payout() {
    let mut e = env(3);
    let b = funded(&mut e, 1, 2);
    approve(&mut e, 0, b, [9; 32]).unwrap();
    approve(&mut e, 1, b, [9; 32]).unwrap();
    // A third approval after payout must not pay again.
    assert!(approve(&mut e, 2, b, [9; 32]).is_err());
    assert_eq!(e.svm.get_balance(&e.contributor).unwrap(), REWARD);
}

#[test]
fn double_funding_rejected() {
    let mut e = env(1);
    let b = funded(&mut e, 1, 1);
    let before = e.svm.get_balance(&b).unwrap();
    let sponsor = e.sponsor.insecure_clone();
    assert!(send(&mut e.svm, fund_ix(&sponsor.pubkey(), 1), &sponsor).is_err());
    assert_eq!(e.svm.get_balance(&b).unwrap(), before);
}

#[test]
fn approval_requires_funding() {
    let mut e = env(1);
    let ix = create_ix(&e, 1, 1, now(&e.svm) + DAY);
    let sponsor = e.sponsor.insecure_clone();
    send(&mut e.svm, ix, &sponsor).unwrap();
    let b = pda(&sponsor.pubkey(), 1);
    assert!(approve(&mut e, 0, b, [9; 32]).is_err());
}

#[test]
fn invalid_parameters_rejected() {
    let mut e = env(2);
    let sponsor = e.sponsor.insecure_clone();
    // threshold above reviewer count
    let ix = create_ix(&e, 1, 3, now(&e.svm) + DAY);
    assert!(send(&mut e.svm, ix, &sponsor).is_err());
    // threshold zero
    let ix = create_ix(&e, 2, 0, now(&e.svm) + DAY);
    assert!(send(&mut e.svm, ix, &sponsor).is_err());
    // deadline in the past
    let ix = create_ix(&e, 3, 1, now(&e.svm) - 1);
    assert!(send(&mut e.svm, ix, &sponsor).is_err());
    // duplicate reviewers
    e.reviewers[1] = e.reviewers[0].insecure_clone();
    let ix = create_ix(&e, 4, 1, now(&e.svm) + DAY);
    assert!(send(&mut e.svm, ix, &sponsor).is_err());
}

#[test]
fn expired_bounty_refunds_and_cannot_pay() {
    let mut e = env(1);
    let b = funded(&mut e, 1, 1);
    let sponsor = e.sponsor.insecure_clone();

    assert!(send(&mut e.svm, refund_ix(&sponsor.pubkey(), 1), &sponsor).is_err(), "refund before deadline");

    warp(&mut e.svm, DAY + 1);
    assert!(approve(&mut e, 0, b, [9; 32]).is_err(), "approve after deadline");

    let before = e.svm.get_balance(&sponsor.pubkey()).unwrap();
    send(&mut e.svm, refund_ix(&sponsor.pubkey(), 1), &sponsor).unwrap();
    let after = e.svm.get_balance(&sponsor.pubkey()).unwrap();
    assert_eq!(after, before + REWARD - 5_000); // minus the tx fee
    assert_eq!(state(&e.svm, &b).status, BountyStatus::Refunded);

    assert!(send(&mut e.svm, refund_ix(&sponsor.pubkey(), 1), &sponsor).is_err(), "double refund");
}

#[test]
fn only_sponsor_can_refund() {
    let mut e = env(1);
    funded(&mut e, 1, 1);
    warp(&mut e.svm, DAY + 1);
    let impostor = Keypair::new();
    e.svm.airdrop(&impostor.pubkey(), SOL).unwrap();
    // PDA derived from the real sponsor, signed by the impostor.
    let mut ix = refund_ix(&e.sponsor.pubkey(), 1);
    ix.accounts[0].pubkey = impostor.pubkey();
    assert!(send(&mut e.svm, ix, &impostor).is_err());
}

#[test]
fn paid_bounty_cannot_be_refunded() {
    let mut e = env(1);
    let b = funded(&mut e, 1, 1);
    approve(&mut e, 0, b, [9; 32]).unwrap();
    warp(&mut e.svm, DAY + 1);
    let sponsor = e.sponsor.insecure_clone();
    assert!(send(&mut e.svm, refund_ix(&sponsor.pubkey(), 1), &sponsor).is_err());
}
