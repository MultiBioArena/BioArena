"""Read-only forward evidence reports from predictions recorded before their labels."""
import json
import math
from pathlib import Path
import sqlite3


def finite(value):return isinstance(value,(float,int)) and math.isfinite(value)


def prediction_metrics(rows):
    valid=[r for r in rows if all(finite(r.get(k)) for k in ('active_prediction_bps','training_target_bps','input_observed_at','observed_at'))
           and r['input_observed_at']<r['observed_at']]
    if not valid:return {'samples':0,'excluded':len(rows)}
    error=sum((r['active_prediction_bps']-r['training_target_bps'])**2 for r in valid)/len(valid)
    zero=sum(r['training_target_bps']**2 for r in valid)/len(valid)
    return {'samples':len(valid),'excluded':len(rows)-len(valid),'active_mse_bps2':error,
            'zero_mse_bps2':zero,'improvement_vs_zero':1-error/zero if zero else None,
            'first_input_at':min(r['input_observed_at'] for r in valid),
            'last_label_at':max(r['observed_at'] for r in valid),
            'definition':'Clipped hypothetical long target; costs and downside penalty already included'}


def portfolio_metrics(rows):
    rows=sorted(rows,key=lambda r:r['observed_at'])
    clean=[r for r in rows if not r.get('valuation_stale',True)
           and finite(r.get('equity_before')) and r['equity_before']>0
           and finite(r.get('equity_after')) and r['equity_after']>=0]
    if not clean:return {'samples':0,'excluded':len(rows)}
    first,last=clean[0]['equity_before'],clean[-1]['equity_after']
    peak=first;drawdown=0
    for row in clean:
        peak=max(peak,row['equity_before'],row['equity_after'])
        drawdown=max(drawdown,1-row['equity_after']/peak)
    return {'samples':len(clean),'excluded':len(rows)-len(clean),'opening_equity':first,'closing_equity':last,
            'net_pnl_usd':last-first,'net_return_pct':(last/first-1)*100,'sampled_max_drawdown_pct':drawdown*100,
            'first_input_at':clean[0].get('observed_at_before',clean[0].get('created_at')),
            'last_observed_at':clean[-1]['observed_at'],
            'costs':'Already reflected in equity; no second subtraction',
            'scope':'Marked paper account span; stale samples excluded; drawdown sampled at recorded decisions'}


def report(run_dir):
    run_dir=Path(run_dir)
    manifest=json.loads((run_dir/'manifest.json').read_text())
    with sqlite3.connect(f'file:{run_dir}/events.sqlite?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result={}
        for bio in manifest['connectomes']:
            samples=[json.loads(r[0]) for r in db.execute('SELECT payload FROM experiences WHERE bio_id=? ORDER BY ts,id',(bio,))]
            inputs=sorted(r['input_observed_at'] for r in samples if finite(r.get('input_observed_at')))
            cutoff=inputs[min(len(inputs)-1,int(len(inputs)*.8))] if inputs else None
            later=[r for r in samples if cutoff is not None and r.get('input_observed_at',-math.inf)>=cutoff]
            accounts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM account_outcomes WHERE bio_id=? ORDER BY ts,id',(bio,))] if 'account_outcomes' in tables else []
            promotions=[json.loads(r[0]) for r in db.execute('SELECT payload FROM model_events WHERE bio_id=? ORDER BY ts,id',(bio,))] if 'model_events' in tables else []
            result[bio]={'all_recorded_predictions':prediction_metrics(samples),
                         'latest_20_percent_by_input_time':prediction_metrics(later),
                         'late_window_starts_at':cutoff,'portfolio':portfolio_metrics(accounts),
                         'model_evaluations':len(promotions),'model_promotions':sum(bool(r['accepted']) for r in promotions)}
        decision_sequence=db.execute('SELECT COALESCE(MAX(seq),0) FROM decisions').fetchone()[0]
    return {'run_id':manifest['run_id'],'decision_sequence':decision_sequence,'bios':result,
            'scope':'Forward recorded predictions and net paper outcomes; no retraining and no effect on active weights',
            'limitations':['The last 20% is descriptive monitoring, not an untouched holdout for this adaptive system.',
                           'Overlapping token labels are correlated; no statistical significance is claimed.',
                           'Lower prediction error does not demonstrate profitability or live executability.',
                           'Execution costs are estimates; longer runs and independent seed/baseline experiments remain necessary.']}
