import pytest
from bio_arena.evaluation import portfolio_metrics,prediction_metrics


def test_forward_predictions_exclude_invalid_times_and_compare_zero_baseline():
    row=dict(active_prediction_bps=10,training_target_bps=20,input_observed_at=1,observed_at=301)
    report=prediction_metrics([row,{**row,'input_observed_at':302}])
    assert report['samples']==1 and report['excluded']==1
    assert report['active_mse_bps2']==100 and report['improvement_vs_zero']==.75


def test_net_account_report_does_not_subtract_fees_twice_or_use_stale_marks():
    rows=[dict(observed_at=100,equity_before=100,equity_after=99,valuation_stale=False),
          dict(observed_at=200,equity_before=99,equity_after=98,valuation_stale=False),
          dict(observed_at=300,equity_before=98,equity_after=1,valuation_stale=True)]
    report=portfolio_metrics(rows)
    assert report['net_pnl_usd']==-2
    assert report['net_return_pct']==pytest.approx(-2)
    assert report['sampled_max_drawdown_pct']==pytest.approx(2)
    assert report['excluded']==1
