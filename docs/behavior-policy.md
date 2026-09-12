# Trading and secondary behavior

Status: implemented, tested and active in the paper backend, 2026-09-11. A controlled migration retained existing accounts and learned models. The frontend now receives recorded activity events from the running service.

`ActivityPolicy` runs once per second independently of trading workers. It observes fresh market data and held-token marks, account activity, pause state, pending decision/settlement, upcoming check time, and risk exits. Its random stream is derived separately from the learner and LIF streams. It does not add neural simulation steps, choose trades, update rewards or delay settlement.

| State | Trigger | Presentation |
| --- | --- | --- |
| Attentive | Risk exit, pending evaluation/execution, check due within five seconds, recent fill | Remain at the controls |
| Returning | Alert, pause, inactive account or stale data during an excursion | Return promptly; backend execution continues |
| Observing | Fresh context without a current alert, or waiting for data | Watch the candidate screens |
| Exploring | Sufficient time until the next check, no alert, activity budget available | Brief species-specific walk or flight |
| Resting | Paused experiment or inactive account | Remain at the desk |

An excursion lasts 5–12 seconds including the return. At least 60 seconds elapse between excursions. Away time is limited to 60 seconds in a rolling 600-second window; the complete planned trip is reserved before departure. Alerts shorten the trip to a return of at most three seconds in the policy. Frontend motion interpolates from the actual position and may finish its smooth return while trading continues. Reduced motion parks the model, and old excursions do not queue for replay on hidden-page return.

State changes are stored separately in SQLite `activity_events`, with identity, version, event ID, reason, start/end time and `presentation_only: true`. The current state is included per Bio in `/api/state`. Policy history and RNG are included in new recovery bundles. The display labels Exploring, Returning to desk and Resting remain separate from BUY/SELL fill results.

This is an engineered presentation policy, not a learned movement strategy or a model of biological fatigue. Prop animations and geometric routes remain presentation code. Tests cover independent timing, strict away-time budget, interruption priority, stale-data suppression, checkpoint continuation and recorded-state frontend playback. See [recovery](recovery-and-evaluation.md) for the legacy-run activation constraint.

## Larva display clarification

The current Larva view places all 3,016 simulated neurons using curated hemisphere and homologous-pair annotations. There are 1,501 left and 1,515 right cells; 2,788 cells have pair IDs. The processed graph contains 32,709 directed cross-side connections out of 107,344 directed connections. Its two longitudinal ribbons and spacing are deterministic display coordinates, not measured anatomy and not a complete ventral nerve cord. The simulator remains one network model; display separation does not partition the simulation.

The left/right relationship is supported by the dataset and the [bilateral-connectome study](https://elifesciences.org/articles/83739). It does not imply perfect symmetry. See [geometry provenance](data-sources.md) and `scripts/build_neural_geometry.py`.

A modest future visual improvement is to reduce the central gap and emphasize actual cross-side edges on cell selection. Retain existing node IDs, activity and graph edges. A measured anatomical view would require acquiring and mapping matching coordinates; merely shaping the current points like a brain would still be an illustration.
