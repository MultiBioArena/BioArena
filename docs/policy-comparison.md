# Conditional policy comparison

The comparison runner tests independent neural-noise seeds and four paper controls against one immutable market tape. It does not update the deployed learners or accounts.

```bash
.venv/bin/python scripts/compare_policies.py active \
  --observations 1000 --seeds 20260911 20260912 20260913 \
  --output output/comparison-example
```

The output directory must be new. SQLite is read under a consistent read transaction. Only decisions whose entire observed candidate slate is captured are included. The quote tape is frozen before any seed runs, and the report records its hash, source run, code hashes and parameters. Preserve both `tape.json` and `results.json` for audit.

| Control | Behavior |
| --- | --- |
| Adaptive | Fresh independent readout learner; delayed labels and chronological candidate promotion |
| Fixed neural | Frozen neural/momentum bootstrap formula; no learned coefficient updates |
| Momentum | Past five-minute movement minus modeled costs |
| Cash | No positions and no trades |

Each seed resets three independent real LIF brains with their original connectome and fixed synthetic calibration. Neural outputs are shared across the policy controls within that seed. The three trading controls share allocation, risk exits, cooldowns and small paper exploration settings; independent account states may lead to different later actions. A fixed policy means a fixed formula, not constant neural activity or an absence of exploration.

Fills use the first available matching quote strictly after the decision, subject to quote expiry and the existing paper broker's costs and risk checks. A future quote cannot fill an earlier timestamp. Fees already reduce account equity and are not subtracted twice. Stale ending marks suppress the reported return. Drawdown is sampled and can miss interim extremes.

The prediction MSE for Adaptive measures the saved readout estimate at observation time, including its initial zero estimate. Entry decisions use the bootstrap until an active model is promoted. MSE therefore does not directly measure the full trading policy. Labels are delayed hypothetical token outcomes, including observations that were never bought.

## First completed comparison

On 2026-09-11, the first frozen tape covered approximately 40.3 minutes, 720 neural observations and 221 complete decisions. Three seeds produced nine Bio/seed outcomes for each control. Mean net percentage returns across the seeds were:

| Bio | Adaptive | Fixed neural | Momentum | Cash |
| --- | ---: | ---: | ---: | ---: |
| Worm | -0.4986% | -0.7265% | -0.2609% | 0% |
| Fly | -0.2150% | -0.2352% | -0.2336% | 0% |
| Larva | -0.1976% | -0.2011% | -0.1976% | 0% |

Adaptive lost less than the fixed control on average in this tape; every Bio's mean remained below cash. This is not evidence of reliable profitability. No deployed coefficients were tuned from these results.

The candidate slates, feature histories and eligibility observations come from the original arena. They are selection-biased and are not independent token discovery by each hypothetical policy. Coverage may omit an asset an alternative policy would later hold. These are conditional policy experiments with fresh benchmark accounts and learners, not an exact replay of production decisions or a pristine out-of-sample evaluation. Longer forward windows, varied market conditions and a separately frozen evaluation protocol remain necessary.

The [operations schedule](operations.md) continues these comparisons with up to 1,000 observations per Bio every six hours. Scheduled windows may overlap and are not independent statistical samples.

## Extended completed comparison

A second frozen tape, also completed on 2026-09-11, covered 163.4 minutes, 3,000 neural observations and 887 complete decisions. All three seeds completed. The same four controls produced these mean net percentage returns:

| Bio | Adaptive | Fixed neural | Momentum | Cash |
| --- | ---: | ---: | ---: | ---: |
| Worm | -1.0402% | -1.4563% | -0.9272% | 0.0000% |
| Fly | -0.2379% | -1.6218% | -0.9577% | 0.0000% |
| Larva | -1.3557% | -1.4062% | -1.2603% | 0.0000% |

Adaptive improved on the fixed neural control in each Bio's seed average, but every Bio's mean remained below cash. Fly had two positive seeded outcomes and one larger negative outcome. Seed dependence, shared historical candidate selection and the limited market window prevent a profitability conclusion. This longer tape overlaps the first window; the two reports are not independent experiments.

Frozen tape SHA-256: `0ff161ca7791983969089474165c369943e8f4806897f389ae8f5e6e30edbe1d`. The local artifact retains the complete parameters, per-seed results, fills, model summaries and distinct neural spike hashes. All recorded fills follow their originating decision timestamps.

The extended run took 35.3 minutes on its one-core service quota. The scheduled job now allows 45 minutes; the active paper arena continued throughout.
