import pytest

from bio_arena.auto_execution import AutoExecutor, ExecutionLimits, ExecutionStore
from bio_arena.execution_trial import ExecutionTrial


ASSET='robinhood:0x'+'1'*40


def decision(key,action,at=100,bio='adult'):
    return {'id':key,'bio_id':bio,'created_at':at,'action':action,'reason':'Bio readout',
        'asset':{'asset_id':ASSET,'chain':'robinhood','address':ASSET.split(':')[1]},
        'policy':{'exploration':False},'intent':{'action':action,'asset_id':ASSET}}


class Adapter:
    def __init__(self):self.clicks=0;self.timeout=False
    def execute(self,intent,limits,live):
        self.clicks+=1
        if self.timeout:return {'status':'unknown','clicked':True}
        buy=intent['action']=='BUY'
        return {'status':'filled','clicked':True,'account_ref':intent['account_ref'],'asset_id':ASSET,
            'action':intent['action'],'relay_status':'SUCCESS','route_id':intent['id'],
            'observed_at':intent['created_at']+1,'balances_verified':True,'cash_delta_usd':-2 if buy else 1.8,
            'position_after':{'asset_id':ASSET,'raw_quantity':'2000','decimals':3} if buy else None}


def setup(tmp_path):
    store=ExecutionStore(tmp_path/'ledger.sqlite','live',{'adult':'a','worm':'b'},ExecutionLimits())
    trial=ExecutionTrial(store,'first','adult',99,3600)
    adapter=Adapter();worker=AutoExecutor(store,adapter,clock=lambda:101,trial_id=trial.id)
    return store,trial,adapter,worker


def test_one_round_trip_stops_and_completed_identity_cannot_trade_again(tmp_path):
    store,trial,adapter,worker=setup(tmp_path)
    buy=decision('buy','BUY');assert trial.accepts(buy,101)
    worker.process(buy)
    assert trial.state(102)['phase']=='waiting_sell'
    assert not trial.accepts(decision('buy-again','BUY'),102)
    assert not trial.accepts(decision('worm','SELL',bio='worm'),102)
    assert not trial.accepts(decision('hold','HOLD'),102)
    sell=decision('sell','SELL',at=300);worker.clock=lambda:301
    assert trial.accepts(sell,301);worker.process(sell)
    result=trial.state(302)
    assert result['complete'] and result['phase']=='complete'
    assert result['real_orders_verified']==2 and result['cash_change_usd']==pytest.approx(-0.2)
    assert result['routes']==['buy','sell'] and store.holding('adult') is None
    store.close()
    store=ExecutionStore(tmp_path/'ledger.sqlite','live',{'adult':'a','worm':'b'},ExecutionLimits())
    resumed=ExecutionTrial(store,'first','adult',500,3600)
    assert resumed.state(501)==result
    assert not resumed.accepts(decision('extra','BUY',500),501) and adapter.clicks==2
    store.close()


def test_trial_deadline_unknown_and_changed_limits_are_not_success(tmp_path):
    store,trial,adapter,worker=setup(tmp_path)
    assert trial.state(3700)['phase']=='expired' and not trial.state(3700)['complete']
    assert not trial.accepts(decision('late','BUY',3700),3700)
    with pytest.raises(ValueError,match='immutable'):ExecutionTrial(store,'first','adult',100,7200)
    with pytest.raises(ValueError,match='Resume'):ExecutionTrial(store,'second','adult',100,3600)
    adapter.timeout=True;worker.process(decision('uncertain','BUY'))
    assert trial.state(102)['phase']=='review_required'
    assert not trial.accepts(decision('retry','BUY'),102)
    store.close()


def test_restart_while_holding_waits_for_own_sell_and_does_not_buy_twice(tmp_path):
    store,trial,adapter,worker=setup(tmp_path);worker.process(decision('buy','BUY'))
    store.close();store=ExecutionStore(tmp_path/'ledger.sqlite','live',{'adult':'a','worm':'b'},ExecutionLimits())
    trial=ExecutionTrial(store,'first','adult',200,3600)
    assert trial.state(200)['phase']=='waiting_sell'
    wrong=decision('wrong','SELL',200);wrong['asset']['asset_id']='other'
    assert not trial.accepts(wrong,201)
    assert trial.state(3700)['phase']=='expired' and store.holding('adult') is not None
    store.close()


def test_missing_sell_evidence_never_completes_the_trial(tmp_path):
    store,trial,adapter,worker=setup(tmp_path);worker.process(decision('buy','BUY'))
    # A disappearance caused by another program or external activity is not an exit receipt.
    with store.db:store.db.execute('DELETE FROM holdings')
    assert trial.state(102)['phase']=='review_required'
    assert not trial.state(102)['complete']
    store.close()


def test_uncertain_exit_keeps_verified_entry_count_and_does_not_repeat(tmp_path):
    store,trial,adapter,worker=setup(tmp_path);worker.process(decision('buy','BUY'))
    worker.clock=lambda:301;adapter.timeout=True
    worker.process(decision('sell','SELL',300))
    state=trial.state(302)
    assert state['phase']=='review_required' and state['real_orders_verified']==1
    assert not state['complete'] and not trial.accepts(decision('retry','SELL',300),302)
    assert store.holding('adult') is not None and adapter.clicks==2
    store.close()
