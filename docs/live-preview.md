# Live execution preview

The production website remains the paper arena. An opt-in preview adds observations from the separately started FOMO executor. Deploying this panel does not enable accounts, submit trades or change execution limits.

## What the preview shows

- Each Bio's reported trial state, executor-owned holdings, verified fills and blocked attempts.
- The selected Bio's latest paper-policy signal and reason, separately from real order outcomes.
- The trial deadline, configured entry size and the absolute fee limit and any enabled percentage limit.
- The latest 40 real order attempts, filterable by Bio, with available quoted fees and verified cash changes.
- Stale, unavailable, pending, completed and expired states. An expired trial can still have a holding.

Operator-started execution acceptance checks are labeled separately. During such a check, the panel shows the explicit BUY/full-SELL test stage instead of presenting the latest paper-policy signal as its cause. A rejected order is an incomplete check, not successful validation.

The three main studio monitors can also show [actual FOMO browser snapshots](fomo-browser-screens.md), with a larger read-only view on click. Creatures stay at their desks and replay newly verified real fills. Candidate screens, portfolios, neural displays and equity remain paper data. Private browser pages are hidden and stale frames are removed.

Strategy trials also display observed BUY/SELL/HOLD counts, filtered signals, blocked attempts and verified fills. Reasons such as paper exploration or a different held token explain why a decision never became an order. Historical order rows identify their source as an execution check, Bio entry policy or real-position exit, so receipts from the first test cannot be mistaken for strategy trades in the second.

Main studio monitors show actual browser frames and gestures replay newly verified real fills. Candidate screens, paper portfolios, neural traces and equity charts continue to follow the paper experiment. There is no live equity curve or live fill feedback into training yet. A recorded empty holding means the executor owns no position in its ledger; it is not an independently refreshed inventory of every manual account action.

## Paper and current live execution

| Mechanism | Paper arena | Current live executor |
| --- | --- | --- |
| Decision source | Independent Bio neural states and learned readouts | Follows those paper-policy intents |
| Portfolio context | Each Bio's paper cash and up to five holdings | Separate real ledger, up to two holdings and one unresolved order per account |
| Sizing | Policy-based allocation | Fixed configured buy input, maximum 10 USD |
| Exploration | Bounded random paper exploration | Excluded by default; explicitly configurable |
| Pricing and costs | DEX reference quotes and modeled costs | FOMO route quotes, separate fee and impact gates |
| Settlement | Simulated broker fill | Matching FOMO Relay success and account balance changes |
| Supported execution | Candidates across the discovery networks | Six registered FOMO networks, subject to executable quotes |
| Learning feedback | Delayed hypothetical outcome labels | Real fill outcomes not yet fed into the learner |
| Trial lifecycle | Continuous experiment | Legacy single cycle or managed entries with persistent exits |

Fee gates compare the quote's cost components with the absolute cap and any enabled percentage cap. An explicit null percentage cap leaves the absolute cap in force. The displayed platform percentage alone is insufficient to establish the total quoted cost. Price impact has its own gate, and eventual third-party settlement costs may differ from estimates. FOMO distinguishes its fees from third-party costs in its [terms, section 7](https://fomo.family/terms).

## Run and build

The existing read-only market display service also provides `GET /api/execution`:

```bash
.venv/bin/uvicorn bio_arena.market_board:app --host 127.0.0.1 --port 8142
```

It reads `.private/execution/live-status.json` and opens the existing `live.sqlite` with SQLite `mode=ro`. Override the directory with `BIO_ARENA_EXECUTION_DIR` when needed. Only an explicit field allowlist is published: profile identities, custody wallets, account references, session IDs, route IDs and raw browser errors are excluded. There is no trading or account-control endpoint.

Build the preview explicitly:

```bash
cd frontend
VITE_EXECUTION_PREVIEW=true VITE_ARENA_TRANSPORT=poll npm run build
```

Route `/api/execution` to the display service alongside `/api/market-board`. Preview deployment uses `VITE_EXECUTION_PREVIEW=true` as a build variable. The default build omits the panel, and a preview must not be promoted to the production domain until the operator chooses to do so. `VITE_EXECUTION_PREVIEW` is a display setting; it is unrelated to starting the [live executor](execution-preparation.md).

The browser polls every three seconds. Report age above 120 seconds is stale; the threshold allows for an in-flight browser attempt lasting up to 110 seconds. A browser connection error marks the display stale immediately. Neither stale data nor a missing ledger is treated as evidence of an empty real account or a completed round trip.

## Verification

Python checks cover private-field exclusion, read-only journal access, unresolved attempts, missing/corrupt evidence and rejection of POST requests. Browser checks cover narrow screens, filtering, held/completed states and stale/network-failure states using isolated response fixtures. These checks do not submit real orders and are separate from a funded round-trip verification.

Managed trials show every recorded holding. The entry deadline stops buying; it does not end exit management. See [managed positions](managed-positions.md) for persistent exits, actual cost-basis checks and remaining funded verification.
