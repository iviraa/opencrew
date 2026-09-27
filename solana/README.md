# Crewly bounty program (Solana devnet)

The on-chain half of `/bounties`. A sponsor escrows a SOL reward in a per-bounty PDA; up to three reviewer
wallets approve one evidence commitment; when the approval threshold is met, the same transaction pays the
contributor. After the deadline an unpaid bounty can only be refunded to its sponsor. Devnet only.

| Instruction | Signer | Effect |
|---|---|---|
| `create_bounty` | sponsor | Creates the bounty PDA `["bounty", sponsor, bounty_id_le]` with reward, deadline, reviewers (1–3) and threshold |
| `fund_bounty` | sponsor | Moves `reward_lamports` from the sponsor into the PDA. Only once |
| `approve_submission` | reviewer | Records this reviewer's approval of `(submission_commitment, contributor)`. All approvals must match. At the threshold, pays the contributor |
| `refund_expired` | sponsor | After the deadline, returns the reward if it was never paid |

Only 32-byte SHA-256 commitments and wallet addresses go on-chain. Evidence, exact locations and the text of a
bounty stay in the Crewly backend (`backend/app/bounties`).

## Toolchain

Installed with the official installer from <https://solana.com/docs/intro/installation>:

```sh
curl --proto '=https' --tlsv1.2 -sSfL https://solana-install.solana.workers.dev | bash
```

Tested with Rust 1.98.1, Solana CLI 3.1.10 (Agave), Anchor 1.1.2 and Surfpool 1.6.0.

## Build and test

```sh
cd solana
anchor build          # target/deploy/crewly_bounty.so and target/idl/crewly_bounty.json
cargo test            # LiteSVM tests in programs/crewly_bounty/src/tests.rs, run against the built .so
```

## Regenerate the TypeScript client

After any change to the program's instructions or accounts:

```sh
cd solana
npm install
anchor build
npm run codama        # writes frontend/src/bounties/generated
```

## Deploy to devnet

```sh
solana config set --url devnet
solana balance                     # the deployer needs about 3 devnet SOL (faucet.solana.com)
anchor deploy --provider.cluster devnet
```

The program ID comes from `target/deploy/crewly_bounty-keypair.json`, which is git-ignored. **Back it up
outside the repo**: without it the program cannot be upgraded at the same address. The deployer wallet is
`~/.config/solana/id.json`, also outside the repo. After deploying, set `SOLANA_PROGRAM_ID` in the backend's
environment to the ID in `Anchor.toml`.
