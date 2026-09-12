# Development guide

## Project structure

| Directory | Responsibility |
| --- | --- |
| `src/bio_arena/` | Neural simulation, market adapters, portfolios, learning, API |
| `frontend/src/` | React dashboard, Three.js studio, neural views |
| `frontend/public/connectomes/` | Display geometry and source manifests |
| `configs/` | Baseline and multi-token experiment settings |
| `scripts/` | Data preparation, calibration, launch, replay, checks |
| `tests/` | Numerical, accounting, data, and lifecycle verification |

Downloaded data, browser storage, logs, and experiment outputs are local artifacts and are excluded from version control.

## Data and calibration

Run the preparation steps in the README before the simulation or data-dependent tests. Downloads are pinned to public source versions and recorded with hashes. Preprocessing retains original neuron identities and documents assumptions. Calibration uses fixed synthetic stimuli, not trading outcomes.

Recalibrate after changes to LIF constants, seeds, simulation windows, or readout denominators. Startup verifies data fingerprints and calibration signatures. Display coordinates are exported separately from the neural graph.

## Validation

```bash
.venv/bin/pytest -q
node scripts/check_desk_playback.mjs
node scripts/check_desk_motion.mjs
node scripts/check_candidate_screens.mjs
cd frontend
npm run build
```

The `requires_data` marker identifies tests needing downloaded graphs. `pytest -q -m 'not requires_data'` runs the remaining suite without scientific downloads or a browser login. The shared `bash scripts/check.sh` command runs that offline suite plus frontend checks. After data preparation, `bash scripts/check.sh --full` includes the scientific tests. Neither command installs dependencies, starts a live arena, or accesses a logged-in browser.

Decision history uses indexes for global ordering and per-agent pagination. Candidate sorting reads review timestamps without adding unobserved tokens to the cache. Application shutdown releases arena resources even when the lifespan exits through an exception. These changes are covered by `tests/test_runtime_regressions.py`.

Tests cover LIF dynamics, deterministic observations, independent accounts, contract identity, cost arithmetic, position limits, causal labels, model promotion, quote freshness, selected connections, and experiment lifecycle. Animation checks cover independent motion, interrupted returns, quiet HOLD, and correct fill presentation.

## Recording and replay

Each run writes source quotes and candidate snapshots, SQLite observations/decisions/fills/experience, model state, and neural checkpoints under `runs/`. New decision-boundary recovery bundles support explicit child-run recovery with `BIO_ARENA_RESUME=RUN_ID`; ordinary legacy checkpoints remain audit artifacts; a paused final checkpoint can use the explicit, validated migration path. See [recovery and evaluation](recovery-and-evaluation.md).

```bash
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/replay.py RUN_ID --steps 20
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/replay_fomo.py RUN_ID --observations 24
.venv/bin/python scripts/export_training.py RUN_ID --output output/training.jsonl
```

Choose the replay command matching the run's market mode. Replay verifies recorded inputs, features, neural-count hashes, readouts, and fill arithmetic. Exact reproduction requires matching source, data, configuration, and numerical dependencies; cross-architecture bitwise equality is not guaranteed.

## Serving the application

The Python service maintains the experiment and must run as a single worker. `scripts/serve.sh` uses a process lock and accepts `BIO_ARENA_CONFIG`, `BIO_ARENA_HOST`, and `BIO_ARENA_PORT` overrides.

During development, Vite proxies `/api` and `/ws` to the arena and `/api/market-board` to the optional display service. For a production build, serve `frontend/dist` and configure equivalent API routing to your own backend. Keep experimental controls restricted; the public dashboard is an observation surface.

## Scope of changes

Useful contributions include stronger replay tooling, experiment recovery, longer evaluation protocols, clearer source provenance, and efficient rendering. Keep dataset licenses and scientific assumptions explicit. A visual demonstration or lower prediction error should not be described as proven trading profitability.

## Ambient presentation

The page background combines scoped Canvas 2D particles and slow CSS light fields. It is independent of market data and neural telemetry, with no added animation dependency. It stops when the page is hidden or a view is fullscreen; reduced-motion preferences render a static field. Mobile particle counts and canvas pixel density are capped. See [component sources and license](component-sources.md).
