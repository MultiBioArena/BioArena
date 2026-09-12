# Paper recovery and forward evaluation

New runs publish a complete recovery bundle after worker initialization and each completed decision. A temporary directory is written first, including every worker's membrane/current/refractory/delay/RNG state and a parent snapshot of accounts, marks, seen intents, encoders, market caches, scheduler, learners, activity policy and log boundaries. File checksums and a manifest precede the atomic `latest.json` pointer. Two completed bundles are retained.

Only complete decision boundaries are recoverable. An interrupted in-progress decision is excluded from the resumed history. A corrupt or missing file, changed code, changed data, or incompatible configuration prevents restoration. No implicit state migration is attempted. The source experiment remains unchanged.

To recover a compatible stopped paper run:

```bash
BIO_ARENA_RESUME=RUN_ID bash scripts/serve.sh
```

The server uses the saved configuration and creates a new child run ID. It copies the source SQLite history through the recorded row boundaries and JSONL prefixes, pins the neural bundle, and records lineage in its manifest. It restores original quote timestamps; old quotes cannot become fresh by restarting. Pause state is retained. The initial timestamp remains the experiment timestamp, so a timed run does not gain extra time.

Pending delayed learning labels and pending account-transition labels are discarded across downtime: the intervening minimum price and uninterrupted valuations were not observed. Model weights, model version counters and independent random streams are retained. A reconnect does not invent missed experience.

Ordinary legacy `checkpoints/` and `models/` files are not complete recovery bundles. An explicit migration is available only for a paused, gracefully stopped multi-token paper run whose final neural, portfolio, model, stopped-state and SQLite boundaries agree:

```bash
BIO_ARENA_MIGRATE_LEGACY=STOPPED_RUN_ID bash scripts/serve.sh
```

The migration validates data hashes, checkpoint arrays and seeds, learner identity and experience counts, and exact full portfolio equality. It retains financial state, neural state/RNG, learned weights/candidates/RNG, and copied history. Market histories, feature warmup, scheduler RNG/deadlines and activity state restart explicitly. Pending labels spanning the outage are discarded. This is a documented migration, not uninterrupted deterministic replay. It starts paused so the operator can review preservation before resuming. The active deployment completed this transition and a subsequent compatible recovery restart.

For bounded recovery after a server process exits:

```bash
.venv/bin/python scripts/serve_resilient.py --resume STOPPED_RUN_ID
# Later starts use the local active-run pointer:
.venv/bin/python scripts/serve_resilient.py
```

Use `--migrate-legacy STOPPED_RUN_ID` for the one-time transition or `--new` for explicitly new capital. The active-run pointer advances only after publishing a complete bundle. Recovery creates child histories and preserves pause state. Repeated early failures, missing bundles and incompatible code stop recovery; the supervisor never silently creates new cash. The supervisor also detects HTTP hangs and stalled decisions; user services supply boot startup where a persistent user manager is configured. Engine errors stop for review. See [operations](operations.md). A direct restart with no resume/migration options intentionally starts a new experiment.

## Evidence reports

```bash
.venv/bin/python scripts/evaluate_training.py RUN_ID --output output/training-report.json
```

This command opens SQLite read-only and summarizes saved forward predictions versus a zero baseline, chronological late-window error, model evaluations/promotions, and actual net paper-account equity. It never retrains or updates an active model. Portfolio fees are already reflected in equity; the report does not subtract them again. Stale valuations are excluded. Drawdown is sampled at saved decisions and can miss intrainterval extremes.

The last 20% by input time is a monitoring window for an adaptive policy, not an untouched holdout. Correlated, overlapping token labels do not establish statistical significance. A longer paper sample, independent seeds, cash/hold baselines and a fixed-policy comparison remain necessary before claiming profitability. Neural replay and accounting replay verify mechanics rather than strategy quality.

Tests are in `tests/test_recovery.py` and `tests/test_evaluation.py`. The recovery integration test uses real neural workers and synthetic market observations; it does not open FOMO or trade real assets.

## Ongoing local monitoring

```bash
.venv/bin/python scripts/monitor_paper.py --watch
```

Every minute this reads the local paper API and SQLite, writes `output/monitor/latest.json`, daily health JSONL, and `training-latest.json`. It records fresh/stale valuations, decision and learning counters, checkpoint age/retention, backend RSS, database size and disk availability. Reports include a no-trade cash reference. Alerts are local records, not external messages or automatic account actions. Separate verified cold-run archival and scheduled seed/policy comparisons are described in [operations](operations.md) and [policy comparison](policy-comparison.md). Forward outcomes still need time to accumulate. The monitor itself does not retrain or rerun policies.
