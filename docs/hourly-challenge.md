# Hourly challenge and EVM predictions

**Status: implemented for local paper testing, hidden by default, not released on the public dashboard.** We may introduce these features gradually in a future update. Test predictions do not qualify for rewards. Real-order execution, live account valuation and reward distribution are not connected.

The competition is an audience score. Each Bio continues learning to find opportunities after costs and downside risk. Losing a spectator round never changes a learner's reward, positions, exploration or neural parameters.

## One hour, comparable returns

Rounds follow UTC hours. The opening and closing values include cash and marked holdings, with trading fees and modeled execution costs already reflected in equity. Ranking compares **hourly percentage return**, not ending balance, lifetime loss, cash balance or dollars lost.

| Bio | Opening equity | Closing equity | Hourly return |
| --- | ---: | ---: | ---: |
| Worm | $100 | $90 | -10% |
| Fly | $1,000 | $950 | -5% |
| Larva | $10,000 | $9,600 | -4% |

Worm wins this example even though Larva loses more dollars. Without external capital flows, the return is `(closing / opening - 1) × 100`. Each hour gets a new baseline; actual accounts, positions and learning continue without resetting.

Rules in version `hourly-twr-v1`:

- The lowest negative return wins. If nobody loses, there is **no loss winner**.
- Returns equal to six decimal places in percentage points share a tie. At least two eligible Bios are required for a winner.
- An account must be active and have positive opening equity to participate. An account that reaches zero during its round has a -100% return. An inactive or unfunded account sits out subsequent rounds.
- A refill does not erase prior losses. A replenished account must be reactivated by the future account adapter and wait for the next opening. The audience service cannot refill or reactivate an account.
- The paper collector polls every five seconds. Each boundary uses the **first fresh snapshot on or after the UTC hour, within 20 seconds**. All three valuations come from that same response. This is a bounded sampling approximation, not an exact historical valuation at the hour.
- The round stores actual sample timestamps, source sequence and opening/closing equity. Stale held-token marks are rejected. A finished all-cash paper account can retain its final cash value.
- Starting mid-hour creates an unscored warmup. Missing an opening does not create a shortened scored round. Missing a closing boundary or changing the arena run/mode voids an open round; old snapshots cannot settle it.
- Final results are immutable. Restarting the audience service resumes its SQLite rounds and votes. This does **not** add restart recovery to the trading engine.

## Deposits and withdrawals: prepared calculation, future live adapter

Live accounts can have unequal funding and manual refills. External transfers must not become trading profit or loss. The calculation core therefore supports time-weighted return: value each subperiod around a reconciled external flow and geometrically link its returns.

```text
Before deposit: $100 → $90                 factor = 90 / 100
Deposit: +$100; verified $90 → $190         no investment return
After deposit: $190 → $171                 factor = 171 / 190
Hourly return = (0.90 × 0.90 − 1) × 100 = −19%
```

`CapitalFlow` requires a unique event ID, timestamp, signed amount, equity immediately before/after, and a reconciled ledger reference. The calculation rejects inconsistent amounts, duplicate events, missing references and invalid valuation intervals. Trading buys/sells are internal movements and must never be classified as external deposits/withdrawals. Transaction costs remain investment costs; an adapter must separate them from contributed capital.

If investment equity falls to zero before a refill, its result remains -100% for that round. A full voluntary withdrawal has no valid continuing invested-capital denominator; that interval cannot be ranked. A subsequent funded round can start normally. Multiple simultaneous transfers must be reconciled into one boundary event.

**The running collector accepts paper states only.** The current paper ledger has no external transfers. A confirmed ERC-20 scanner, conservative classification ledger and valuation-bound reconciler are now implemented and tested; see [capital-flow evidence](capital-flows.md). They are not connected to complete live FOMO account accounting. Before live scoring, an adapter must prove the complete transfer ledger, value all holdings in a common currency, preserve the supporting evidence, and pass its reconciled flows into scoring. Missing flow evidence must prevent live settlement. Merely setting `mode=live` is rejected.

This design uses the principle of valuing around external cash flows and linking subperiod returns described in the [GIPS calculation methodology](https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/). The experimental arena does not claim GIPS compliance.

## EVM predictions

No wallet connection or signature is requested. A visitor enters a non-zero `0x` address and selects Worm, Fly or Larva. The chain is configured independently: an EVM address alone cannot identify a network. Configure the actual Robinhood launch network's chain ID, RPC and ERC-20 contract; no Ethereum-mainnet or Solana default is assumed.

Three server modes are available:

| Mode | Eligibility | Purpose |
| --- | --- | --- |
| `disabled` | No submissions | Default; future release remains closed |
| `paper_test` | Valid non-zero EVM address | Local paper test; **no holding check or rewards** |
| `token_holder` | Server-verified configured ERC-20 balance | Prepared integration; launch network/contract not configured or verified yet |

The UI is separately hidden unless built with `VITE_AUDIENCE_PREVIEW=true`. There is no query-string shortcut to enable it. The audience service defaults to loopback, and no public challenge route is deployed as part of this update.

Voting opens after the round's valid opening snapshot and locks 15 minutes after the UTC hour. An address has **one equal-weight vote per round**, regardless of balance. Addresses are canonicalized to lowercase and uniquely constrained in SQLite. Repeating the same choice returns the existing receipt; changing it fails. Requests finishing after the cutoff do not count. Per-round gate settings are saved at opening; changing gate settings mid-round requires waiting for the next round.

The ERC-20 check uses fixed, server-selected [JSON-RPC read methods](https://ethereum.org/developers/docs/apis/json-rpc/) and [`balanceOf(address)`](https://eips.ethereum.org/EIPS/eip-20):

1. Verify `eth_chainId` against the configured network.
2. Select the current block minus the configured confirmation count, validate its number/hash and require a block timestamp no older than five minutes.
3. Require deployed contract code and read the balance at that block. Compare exact uint256 raw units; optional token `decimals()` is not required.
4. Read the block hash again and reject a reorg during lookup. Save chain, contract, block number/hash, raw balance, threshold and check time with the vote.

The default threshold is one **raw unit**, meaning any non-zero balance, not one whole token. Configure the threshold for the actual token. The default three-block depth is an implementation setting, not a guarantee of finality on an unverified network. Provider failures, wrong chains, empty contracts, malformed balances and stale blocks fail closed. No private RPC URL is returned or stored in public round rules. There are no transaction/signing RPC methods.

Holding checks occur at submission, not at a common round-wide holder snapshot. They do not prevent transferring tokens between addresses and voting again. **Address entry does not prove ownership**: someone can enter another holder's address first. Rate limiting and one-vote-per-address constraints do not make this person-based voting or authenticated reward eligibility. Before rewards, decide on ownership/claim verification, anti-abuse controls and holding snapshot rules. Nothing in this release distributes assets or promises a reward.

Public endpoints return aggregate counts and round evidence, never a voter directory. A random receipt lets the visitor inspect their prediction outcome with a masked address; it is a bearer reference, not an ownership credential. The browser remembers the last receipt. Raw addresses and holding evidence are stored only in the operator's private SQLite ledger. Retention/deletion and stronger edge abuse controls should be finalized before a public holder-voting release.

## Local preview

Use prepared project dependencies and an already-running paper arena. This service never starts, pauses or resets the trading engine.

```bash
# Terminal 1: separate audience process, local-only test votes
BIO_VOTE_MODE=paper_test bash scripts/serve_audience.sh

# Terminal 2: frontend preview; Vite proxies /api/challenge to port 8143
VITE_AUDIENCE_PREVIEW=true VITE_ARENA_TRANSPORT=poll npm run build --prefix frontend
cd frontend
npx vite preview --host 127.0.0.1 --port 4189
```

Only full UTC-hour rounds are scored; a mid-hour start waits for the next opening. For rapid repeated scenarios, run the offline clock-controlled tests. Do not change the system clock or feed synthetic equity into a real arena.

```bash
.venv/bin/python -m pytest -q tests/test_challenge.py tests/test_voting.py
```

See [the environment template](../configs/audience.env.example). The launcher does not auto-load the file: export selected settings in the audience process environment. `BIO_VOTE_RPC_URL` stays server-side. The service uses one worker and a database lock; the SQLite file, WAL files and receipts must remain private and outside Git.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/challenge` | Current round, freshness, aggregate counts and six recent results |
| `GET /api/challenge/rounds/{round_id}` | Stored opening/closing snapshots, rules and score evidence |
| `POST /api/challenge/votes` | `{round_id, address, bio_id}`; no client-provided balances accepted |
| `GET /api/challenge/receipts/{receipt}` | Masked receipt and prediction outcome; rewards always disabled |

The vote endpoint limits request size, rate and concurrent RPC work, and rechecks the cutoff before committing. No proxy headers are trusted by the launcher. A future public reverse proxy needs a considered client-IP/rate-limit design rather than trusting arbitrary forwarded headers.

## Release preparation

1. Keep `VITE_AUDIENCE_PREVIEW` absent/false and `BIO_VOTE_MODE=disabled` after local testing. Stop the preview process. Normal builds contain no active audience panel or polling.
2. Introduce the paper audience feature as a separately announced update if desired. Expose only the audience API paths, retain English test/no-reward labels and monitor round boundaries before enabling holder voting.
3. Configure and verify the actual EVM chain, RPC, token and minimum balance. A mocked ERC-20 test is not proof that the future launch contract works.
4. Prepare isolated real execution, account valuation, complete capital-flow reconciliation, order receipts and balance checks. Existing FOMO logins and paper fills do not establish live execution readiness.
5. Consider live rounds and authenticated reward claims only after those integrations are verified. No automatic switch or distribution is provided.

## Extensible participants and prediction prototype

Each round now freezes its participant IDs in `rules.participants`. A newly observed Bio joins the next round; closing a round requires all of its original account valuations. Removing one voids that round rather than changing the outcome set. The UI and vote validation use the frozen roster. Existing three-Bio records remain compatible.

The separate [offline prediction pool](prediction-market.md) uses non-transferable test points and has no public endpoint or wallet integration. It does not change the hidden address-only voting feature.
