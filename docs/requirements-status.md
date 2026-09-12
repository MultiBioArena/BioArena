# Requirements and verification status

Audit date: 2026-09-12. **The public arena is paper trading. Fly's operator-started funded execution check has passed after recovery; strategy-driven real round trips and the other accounts remain unverified.** Repository implementation, local verification, and active deployment are separate states below.

The earlier paper experiment has been migrated through a validated paused final checkpoint. Cash, holdings, neural state and learned models were retained. Market/feature warmup and scheduler resets are disclosed in the child manifest; a subsequent complete recovery restart also passed. The audience service and prediction sandbox remain hidden and disabled.

| Requirement | Implementation | Verification / remaining work |
| --- | --- | --- |
| Three genuine public connectomes | Implemented and running: Worm 302, Fly 10,000, Larva 3,016 | Source versions, hashes, preprocessing and assumptions recorded; data-dependent tests pass. Three models represent two species. |
| One LIF implementation, independent brains | Implemented and running | Separate worker state, delay buffers, readout, accounts and random streams. Numerical and deterministic continuation tests. |
| Small data / Linux deployment | Implemented | Sparse processed graphs, compiled numerical loop, persistent workers. Local minute-by-minute RSS, database growth, checkpoint and disk monitoring is running; a longer observation period remains necessary. |
| Shared live SOL/USDT feed | Implemented baseline | Independent staggered decisions; available as a separate configuration. |
| FOMO hot-token discovery | Implemented and running | Authenticated rendered Trending subset, not a guaranteed complete ranking. DEX reference quotes are not executable FOMO quotes. |
| Independent token choice, same token allowed | Implemented and running | Per-Bio review rotation, encoders/history per chain and contract, independent learner state. |
| Paper account, maximum five holdings | Implemented and running | Fees, slippage, pool limits, cost basis, partial exits, stale marks, duplicate intents and isolation tested. |
| Profit-oriented learning | Implemented and running | Ten-feature readout, delayed hypothetical targets, chronological candidate validation. Connectome weights remain fixed. No reward for trade count or losing. |
| Proven profitability / live readiness from training | **Not established** | The current paper run is losing money. Prediction-error improvements do not prove profitable decisions. Two three-seed adaptive/fixed/momentum/cash comparisons are complete, including a 163.4-minute tape with 3,000 observations and 887 decisions; mean returns remain below cash. Longer scheduled windows and varied forward conditions remain necessary. |
| Buy / Sell gestures, no Skip press | Implemented and running | Gestures use recorded outcomes. HOLD is quiet. Animation never submits or delays an order. |
| Shared 3D studio, orbit/zoom/fullscreen | Implemented and running | Three procedural creatures, three front screens, eighteen candidate screens, rear rotating market wall and props. |
| Current holdings on the computer screens | Implemented and running | Per-Bio held token selection, automatic focus and recorded-trade focus. |
| Per-Bio and all-Bio decision records | Implemented and running | Pagination and query indexes tested; individual decisions retain input, spikes, policy and fill evidence. |
| Species-specific neural views | Implemented and running | Worm atlas body axis; Fly measured soma cloud; Larva paired schematic ribbons. Select-cell edges, orbit/zoom and fullscreen supported. |
| Measured anatomical coordinates for every cell | **Partial** | Worm 300/302 located. Fly 9,304 simulated coordinates + 4,696 static reference cells; 696 simulated cells lack markers. Larva geometry is organizational, not measured anatomy or a complete nerve cord. |
| English public presentation and repository | Implemented | English README, mechanisms, diagrams, source links and public/private history separation. No login profiles or account identifiers in public assets. |
| Background motion and responsive layout | Implemented and deployed | Scoped particles/light fields; hidden-page and reduced-motion handling. Software rendering is not proof of 30 fps on every device. |
| Livestream presentation | Broadcast layout implemented | Livestreaming is optional and currently out of scope; the normal website runs independently. |
| State-driven wandering and rest | **Implemented and tested in this update** | Separate backend policy and event ledger; at most 60 seconds away per 600 seconds, 5–12-second excursions, at least 60 seconds between. Returns for risk, execution, stale data and upcoming checks. Active server emits behavior events; the deployed frontend consumes them. |
| Complete paper recovery | **Implemented and tested in this update** | Atomic, hashed decision-boundary bundles; real three-worker offline stop/resume test; exact neural continuation. Validated paused-stop legacy migration and a subsequent compatible production recovery passed. Ordinary legacy checkpoints are still rejected as complete bundles. |
| Additional Bio support | **Infrastructure implemented** | Configurable roster (1–16), dynamic accounts/API/filter labels and frozen hourly outcomes. A new Bio still needs a real processed graph, mappings, calibrated readout and geometry. New 3D species models are explicitly pending, not substituted with Larva. |
| Hourly worst percentage-loss winner | Implemented, tested, hidden | UTC boundaries, unequal capital, ties, no-loss rounds, missed snapshots and restarts. No ultimate-elimination race. Learners continue seeking profit. |
| Manual refills / withdrawals without distorting scores | Scanner and reconciliation infrastructure tested | Confirmed configured ERC-20 transfers, conservative classification, durable cursor, bound USD valuation inputs and hourly integration are implemented. Unknown or incomplete evidence prevents scoring. Full FOMO multi-chain coverage and automatic historical USD valuation remain unconnected. |
| EVM address-only voting | Implemented, tested, hidden | One address/round, frozen gate, cutoff, receipts, normalization and failure behavior. Address input does not prove wallet ownership. |
| Real launch-token holding eligibility | Configurable adapter, mocked RPC tests | Actual chain/token/minimum holding not configured. Requires read-only integration checks against the chosen deployed token. |
| Three FOMO login profiles assigned to Bios | Verified privately | All three profiles and custody bindings checked privately. Account balances and identifiers are excluded from public release. Login and quote preparation do not prove a funded trade. |
| One live holding and 10 USD maximum buy | Implemented; disabled by default | A 2 USD initial buy size, hard 10 USD buy-input ceiling, separate fee limits and entry budgets. Full-position SELL is allowed above 10 USD. Paper capital is unchanged. |
| Order preflight and durable intent tracking | **Implemented and locally tested** | Account/contract/amount binding, expiry, cash, fee coverage, up to two holdings, duplicate IDs and unresolved-order blocking. Supplied/imported evidence is not a remote verification. `can_submit` always false. |
| Autonomous FOMO buy/sell and receipt reconciliation | **Fly execution check passed; strategy round trip unverified** | One operator-started BUY/full-SELL pair matched Relay success, exact token quantity, actual cash changes and an empty holding after recovery from earlier defects. The verified exit automatically advanced to a separate policy trial. Other accounts, unattended reliability and strategy-driven execution remain unverified. The opt-in preview shows real receipts; live learning feedback, live equity, automatic late-settlement recovery and independent chain finality remain incomplete. |
| Wallet-funded prediction market | Offline test-point pool implemented; **real market not built** | Proportional pool, immutable results, tie/no-loss/void/no-winning-stake refunds, restart and integer conservation tested. No wallet, contract, real collateral, transferable shares, liquidity or payout transaction. |
| Voting rewards / token distribution | **Not built or enabled** | Requires ownership proof, eligibility/snapshot policy, allocation rules and an authorized distribution path. Current votes are not claims. |
| Forward evaluation reporting | **Implemented and monitored continuously** | Saved predictions versus zero baseline and actual net paper equity; no double subtraction of costs. Latest 20% is descriptive monitoring, not an untouched test set. |
| Boot startup / hangs / archival | Implemented and activated | User services enabled; controlled server suspension recovered with balances, holdings and learning preserved. Daily verified cold-run compression and bounded server logs. No whole-host reboot or off-host backup test. |
| Project custom domain | Bound to the existing frontend | `multibioarena.fun` serves HTTPS; DNS, homepage, API health and the `www` permanent redirect verified. [Setup](domain.md). |
| Vercel deployment / second account | Existing deployment works | A second account was not connected in this audit; no free-tier capacity promise. The simulation requires a persistent backend separate from the frontend deployment. |

## New verification coverage

- Real connectome checkpoints reproduce subsequent spike hashes, scores, neural activity and random state for all three Bios.
- A real three-worker experiment on an offline price feed buys paper positions, publishes bundles, stops, forks a child run and continues with the positions intact.
- Corrupt bundles and changed trading code fail closed; source logs and crash tails remain untouched; the resumed child pins its own checkpoint files.
- Learner active/working/candidate weights and RNG resume; pending labels crossing an unobserved outage are discarded explicitly.
- Hourly results retain the opening roster when another Bio arrives; missing frozen participants void settlement.
- Preflight never submits; imported unknown orders cannot be resubmitted or bypassed by preparing another order for the same account.
- Test-point settlement conserves every integer point and cannot pay twice after restart.

## Remaining release gates

1. Completed: controlled legacy migration plus compatible restart, with exact account/holding/learning preservation and explicit reset boundaries.
2. Monitoring, boot services, a tested hang watchdog, verified cold-run archival and six-hour seeded comparisons are active. Both the initial and extended comparisons are complete; long-run profitability and whole-host reboot recovery are not established. Streaming-machine setup is optional.
3. The automatic executor requires operator startup. Fly's first funded BUY/full-SELL acceptance check is complete, with matching quantities, Relay success, verified cash changes and an empty holding. It required recovery from earlier confirmation and UI-control failures. The corrected exit automatically advanced to the policy trial; a strategy-driven pair has not yet passed. Other accounts, independent chain finality, automatic late-settlement recovery, live learning feedback, live equity and unattended reliability remain unverified or incomplete.
4. Set the launch network, token address and holding threshold, then validate real read-only RPC eligibility. Keep the audience module hidden until its planned reveal.
5. Treat wallet-funded prediction trading as a separate release with wallet authentication, collateral accounting, contract implementation, resolution/dispute rules and an independent review. The offline pool is only a mechanism prototype.

See [recovery and evaluation](recovery-and-evaluation.md), [behavior policy](behavior-policy.md), [execution preparation](execution-preparation.md), [hourly challenge](hourly-challenge.md), and [prediction sandbox](prediction-market.md).

Operational details: [service recovery and archival](operations.md), [seeded comparisons](policy-comparison.md), and [capital-flow boundaries](capital-flows.md).

Managed real positions now support two distinct held tokens, durable exit requests, actual entry-cost drawdown checks and continued exits after the entry deadline. These are covered by isolated tests; a funded managed-portfolio pass and live feedback into learning remain pending. See [managed positions](managed-positions.md).
