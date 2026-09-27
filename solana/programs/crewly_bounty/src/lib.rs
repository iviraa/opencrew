//! Crewly damage-verification bounties (devnet only).
//!
//! A sponsor escrows a SOL reward in a per-bounty PDA. Up to three reviewer
//! wallets approve one submission commitment (a SHA-256 of the evidence the
//! Crewly backend keeps off-chain). When `threshold` reviewers have approved
//! the same commitment for the same contributor, the reward is released to
//! that contributor inside the approving transaction. After the deadline, an
//! unpaid bounty can only be refunded to the sponsor.
//!
//! Nothing private goes on-chain: only 32-byte commitments and wallet keys.

use anchor_lang::prelude::*;
use anchor_lang::system_program::{transfer, Transfer};

#[cfg(test)]
mod tests;

declare_id!("4jcrRV3ab8boiXDF6YHdmRu9YwMLzonjuAK9pFSyFZPF");

pub const MAX_REVIEWERS: usize = 3;
pub const BOUNTY_SEED: &[u8] = b"bounty";

#[program]
pub mod crewly_bounty {
    use super::*;

    pub fn create_bounty(
        ctx: Context<CreateBounty>,
        bounty_id: u64,
        reward_lamports: u64,
        deadline: i64,
        rules_commitment: [u8; 32],
        region_commitment: [u8; 32],
        reviewers: Vec<Pubkey>,
        threshold: u8,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        require!(deadline > now, BountyError::DeadlineInPast);
        // The payout lands in a plain wallet that may not exist yet, so the
        // reward alone must keep it rent-exempt.
        require!(
            reward_lamports >= Rent::get()?.minimum_balance(0),
            BountyError::RewardTooSmall
        );
        require!(
            !reviewers.is_empty() && reviewers.len() <= MAX_REVIEWERS,
            BountyError::BadReviewers
        );
        for (i, r) in reviewers.iter().enumerate() {
            require!(!reviewers[..i].contains(r), BountyError::BadReviewers);
        }
        require!(
            threshold >= 1 && (threshold as usize) <= reviewers.len(),
            BountyError::BadThreshold
        );

        let b = &mut ctx.accounts.bounty;
        b.sponsor = ctx.accounts.sponsor.key();
        b.bounty_id = bounty_id;
        b.reward_lamports = reward_lamports;
        b.deadline = deadline;
        b.rules_commitment = rules_commitment;
        b.region_commitment = region_commitment;
        b.reviewers = reviewers;
        b.threshold = threshold;
        b.approvals = 0;
        b.submission_commitment = [0; 32];
        b.contributor = Pubkey::default();
        b.status = BountyStatus::Created;
        b.created_at = now;
        b.funded_at = 0;
        b.settled_at = 0;
        b.bump = ctx.bumps.bounty;
        Ok(())
    }

    pub fn fund_bounty(ctx: Context<FundBounty>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let b = &ctx.accounts.bounty;
        require!(b.status == BountyStatus::Created, BountyError::AlreadyFunded);
        require!(now < b.deadline, BountyError::Expired);
        let amount = b.reward_lamports;

        transfer(
            CpiContext::new(
                System::id(),
                Transfer {
                    from: ctx.accounts.sponsor.to_account_info(),
                    to: ctx.accounts.bounty.to_account_info(),
                },
            ),
            amount,
        )?;

        let b = &mut ctx.accounts.bounty;
        b.status = BountyStatus::Funded;
        b.funded_at = now;
        emit!(BountyFunded { bounty: b.key(), amount });
        Ok(())
    }

    pub fn approve_submission(
        ctx: Context<ApproveSubmission>,
        submission_commitment: [u8; 32],
        contributor: Pubkey,
    ) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let reviewer = ctx.accounts.reviewer.key();
        let b = &mut ctx.accounts.bounty;

        require!(b.status == BountyStatus::Funded, BountyError::NotFunded);
        require!(now <= b.deadline, BountyError::Expired);
        let idx = b
            .reviewers
            .iter()
            .position(|r| *r == reviewer)
            .ok_or(BountyError::NotReviewer)?;
        let bit = 1u8 << idx;
        require!(b.approvals & bit == 0, BountyError::AlreadyApproved);
        require_keys_eq!(
            ctx.accounts.contributor.key(),
            contributor,
            BountyError::WrongContributor
        );

        if b.approvals == 0 {
            b.submission_commitment = submission_commitment;
            b.contributor = contributor;
        } else {
            require!(
                b.submission_commitment == submission_commitment && b.contributor == contributor,
                BountyError::SubmissionMismatch
            );
        }
        b.approvals |= bit;
        let count = b.approvals.count_ones() as u8;
        emit!(SubmissionApproved { bounty: b.key(), reviewer, approvals: count });

        if count >= b.threshold {
            let amount = b.reward_lamports;
            b.status = BountyStatus::Paid;
            b.settled_at = now;
            ctx.accounts.bounty.sub_lamports(amount)?;
            ctx.accounts.contributor.add_lamports(amount)?;
            emit!(RewardReleased { bounty: ctx.accounts.bounty.key(), contributor, amount });
        }
        Ok(())
    }

    pub fn refund_expired(ctx: Context<RefundExpired>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let b = &mut ctx.accounts.bounty;
        require!(b.status == BountyStatus::Funded, BountyError::NotFunded);
        require!(now > b.deadline, BountyError::NotExpired);
        let amount = b.reward_lamports;
        b.status = BountyStatus::Refunded;
        b.settled_at = now;
        ctx.accounts.bounty.sub_lamports(amount)?;
        ctx.accounts.sponsor.add_lamports(amount)?;
        emit!(BountyRefunded { bounty: ctx.accounts.bounty.key(), amount });
        Ok(())
    }
}

#[derive(Accounts)]
#[instruction(bounty_id: u64)]
pub struct CreateBounty<'info> {
    #[account(mut)]
    pub sponsor: Signer<'info>,
    #[account(
        init,
        payer = sponsor,
        space = 8 + Bounty::INIT_SPACE,
        seeds = [BOUNTY_SEED, sponsor.key().as_ref(), &bounty_id.to_le_bytes()],
        bump,
    )]
    pub bounty: Account<'info, Bounty>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct FundBounty<'info> {
    #[account(mut)]
    pub sponsor: Signer<'info>,
    #[account(
        mut,
        has_one = sponsor,
        seeds = [BOUNTY_SEED, sponsor.key().as_ref(), &bounty.bounty_id.to_le_bytes()],
        bump = bounty.bump,
    )]
    pub bounty: Account<'info, Bounty>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ApproveSubmission<'info> {
    pub reviewer: Signer<'info>,
    #[account(
        mut,
        seeds = [BOUNTY_SEED, bounty.sponsor.as_ref(), &bounty.bounty_id.to_le_bytes()],
        bump = bounty.bump,
    )]
    pub bounty: Account<'info, Bounty>,
    /// Receives the reward once the threshold is met. Checked against the
    /// `contributor` argument in the handler.
    #[account(mut)]
    pub contributor: SystemAccount<'info>,
}

#[derive(Accounts)]
pub struct RefundExpired<'info> {
    #[account(mut)]
    pub sponsor: Signer<'info>,
    #[account(
        mut,
        has_one = sponsor,
        seeds = [BOUNTY_SEED, sponsor.key().as_ref(), &bounty.bounty_id.to_le_bytes()],
        bump = bounty.bump,
    )]
    pub bounty: Account<'info, Bounty>,
}

#[account]
#[derive(InitSpace)]
pub struct Bounty {
    pub sponsor: Pubkey,
    pub bounty_id: u64,
    pub reward_lamports: u64,
    pub deadline: i64,
    pub rules_commitment: [u8; 32],
    pub region_commitment: [u8; 32],
    #[max_len(3)]
    pub reviewers: Vec<Pubkey>,
    pub threshold: u8,
    /// Bitmap over `reviewers` indices.
    pub approvals: u8,
    pub submission_commitment: [u8; 32],
    pub contributor: Pubkey,
    pub status: BountyStatus,
    pub created_at: i64,
    pub funded_at: i64,
    /// When the bounty was paid or refunded.
    pub settled_at: i64,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace, Debug)]
pub enum BountyStatus {
    Created,
    Funded,
    Paid,
    Refunded,
}

#[event]
pub struct BountyFunded {
    pub bounty: Pubkey,
    pub amount: u64,
}

#[event]
pub struct SubmissionApproved {
    pub bounty: Pubkey,
    pub reviewer: Pubkey,
    pub approvals: u8,
}

#[event]
pub struct RewardReleased {
    pub bounty: Pubkey,
    pub contributor: Pubkey,
    pub amount: u64,
}

#[event]
pub struct BountyRefunded {
    pub bounty: Pubkey,
    pub amount: u64,
}

#[error_code]
pub enum BountyError {
    #[msg("Deadline must be in the future")]
    DeadlineInPast,
    #[msg("Reward must cover rent exemption for the payout wallet")]
    RewardTooSmall,
    #[msg("Reviewers must be 1 to 3 distinct wallets")]
    BadReviewers,
    #[msg("Threshold must be between 1 and the number of reviewers")]
    BadThreshold,
    #[msg("Bounty is already funded")]
    AlreadyFunded,
    #[msg("Bounty is not in the funded state")]
    NotFunded,
    #[msg("Bounty deadline has passed")]
    Expired,
    #[msg("Bounty deadline has not passed yet")]
    NotExpired,
    #[msg("Signer is not a reviewer for this bounty")]
    NotReviewer,
    #[msg("This reviewer already approved")]
    AlreadyApproved,
    #[msg("Approval does not match the submission other reviewers approved")]
    SubmissionMismatch,
    #[msg("Contributor account does not match the approved contributor")]
    WrongContributor,
}
