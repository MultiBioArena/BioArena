# Hourly prediction market prototype

Status: **offline test points only; hidden and without public endpoints**. No wallet connects, collateral deposits, transferable outcome tokens, contracts, or real-money payouts are implemented.

`PredictionSandbox` tests a proportional outcome pool tied to the existing hourly percentage-loss result. The participant list and opening/rules freeze before entries. A new Bio can enter the next hourly pool. Trading agents still seek profit; audience scoring does not alter their reward.

1. Local fixtures grant non-transferable integer test points.
2. A participant stakes points on an eligible Bio before the hourly entry cutoff (15 minutes).
3. With one loss winner and at least one winning stake, the entire pool is divided among winning stakes in proportion to points contributed. Integer remainders are distributed deterministically; there is no fee.
4. A tie, no-loss result, void round or absence of winning stakes refunds every stake.
5. Grant/stake IDs are idempotent; frozen opening evidence and final settlement cannot be changed. SQLite survives restart, and settlement cannot pay twice.

For example, 10 points on Worm, 20 on Fly and 10 on Larva form a 40-point pool. If Worm alone loses the largest hourly percentage, its stake receives 40 points. This prototype is a pooled prediction mechanism, not an order book or a continuously quoted probability market. Buying outcome shares and reselling them before settlement would require a separate market and liquidity design.

Tests in `tests/test_prediction_sandbox.py` cover settlement, refunds, frozen outcomes, insufficient balances, exact point conservation and duplicate/restart handling. There is no rewards entitlement from these test records or the separate address-only voting feature.

A wallet-funded release still needs a selected network and collateral asset, ownership authentication, contract implementation, wallet transaction flow, deposit/claim reconciliation, resolution and dispute rules, liquidity and an independent review. The current Python sandbox is not a deployable or audited smart contract. No automatic payout path exists.
