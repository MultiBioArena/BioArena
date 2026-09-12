from copy import deepcopy
from dataclasses import asdict
import json
import sqlite3

import pytest

from bio_arena.auto_execution import AutoExecutor, ExecutionLimits, ExecutionStore
from bio_arena.execution_service import current_decisions, load_config


ADDRESS = '0x'+'1'*40
ASSET = 'robinhood:'+ADDRESS


def decision(key='one', bio='worm', action='BUY', at=100):
    return {'id':key, 'bio_id':bio, 'action':action, 'run_id':'run', 'created_at':at,
            'reason':'Bio readout', 'asset':{'asset_id':ASSET,'chain':'robinhood','address':ADDRESS},
            'intent':{'action':action,'asset_id':ASSET,'risk_exit':False},
            'policy':{'exploration':False,'model_version':3}}


def fill(intent, now=101):
    return {'status':'filled','clicked':True,'account_ref':intent['account_ref'],'asset_id':intent['asset_id'],
            'action':intent['action'],'relay_status':'SUCCESS','route_id':'fixture-route','balances_verified':True,
            'observed_at':now, 'position_after':{'asset_id':ASSET,'raw_quantity':'2000000','decimals':6}
            if intent['action']=='BUY' else None}


class Adapter:
    def __init__(self, result=None):
        self.calls=[]
        self.result=result

    def execute(self, intent, limits, *, live):
        self.calls.append((deepcopy(intent), live))
        if self.result == 'timeout':
            raise TimeoutError('Simulated post-click disconnect')
        return self.result or fill(intent, intent['created_at']+1)


def store(tmp_path, mode='live', limits=None):
    return ExecutionStore(tmp_path/'orders.sqlite', mode, {'worm':'a','adult':'b','larva':'c'}, limits or ExecutionLimits())


def test_buy_hold_sell_uses_real_quantity_and_persists(tmp_path):
    ledger=store(tmp_path); adapter=Adapter(); worker=AutoExecutor(ledger,adapter,clock=lambda:101)
    assert worker.process(decision())['status']=='filled'
    assert adapter.calls[0][0]['amount_usd']=='2'
    assert worker.process(decision())['status']=='held'
    assert worker.process(decision('another'))['reason'].startswith('One holding')
    ledger.close(); ledger=store(tmp_path)
    worker=AutoExecutor(ledger,adapter,clock=lambda:301)
    result=worker.process(decision('exit',action='SELL',at=300))
    assert result['status']=='filled' and ledger.holding('worm') is None
    assert adapter.calls[-1][0]['quantity_raw']=='2000000'
    assert len(adapter.calls)==2
    ledger.close()


@pytest.mark.parametrize('outcome', ['timeout', {'status':'unknown','clicked':True}])
def test_unknown_blocks_account_after_restart_but_other_bio_continues(tmp_path, outcome):
    ledger=store(tmp_path); bad=Adapter(outcome)
    assert AutoExecutor(ledger,bad,clock=lambda:101).process(decision())['status']=='unknown'
    ledger.close(); ledger=store(tmp_path); adapter=Adapter()
    worker=AutoExecutor(ledger,adapter,clock=lambda:101)
    assert worker.process(decision('next'))['status']=='held'
    assert worker.process(decision('fly',bio='adult'))['status']=='filled'
    assert len(adapter.calls)==1
    ledger.close()


def test_crash_after_durable_claim_never_resubmits(tmp_path):
    ledger=store(tmp_path); intent,_=ledger.make_intent(decision(),101)
    ledger.claim(intent,101); ledger.close(); ledger=store(tmp_path)
    adapter=Adapter(); worker=AutoExecutor(ledger,adapter,clock=lambda:101)
    assert worker.process(decision())['status']=='held'
    assert worker.process(decision('new'))['status']=='held'
    assert adapter.calls==[]
    ledger.close()


def test_unique_pending_and_immutable_identity(tmp_path):
    ledger=store(tmp_path); intent,_=ledger.make_intent(decision(),101)
    ledger.claim(intent,101)
    changed={**intent,'amount_usd':'3'}
    with pytest.raises(ValueError,match='reused'):ledger.claim(changed,101)
    with pytest.raises(sqlite3.IntegrityError):ledger.claim({**intent,'id':'two'},101)
    ledger.close()
    with pytest.raises(ValueError,match='immutable'):store(tmp_path,mode='shadow')


def test_custody_pins_cannot_change_on_restart(tmp_path):
    path=tmp_path/'custody.sqlite';bindings={'worm':'a'}
    ledger=ExecutionStore(path,'live',bindings,ExecutionLimits(),identities={'worm':{'wallet':'one'}})
    intent,_=ledger.make_intent(decision(),101)
    assert intent['limits']['max_buy_usd']=='10'
    ledger.close()
    with pytest.raises(ValueError,match='immutable'):
        ExecutionStore(path,'live',bindings,ExecutionLimits(),identities={'worm':{'wallet':'two'}})


@pytest.mark.parametrize('change', [
    {'created_at':0}, {'created_at':float('nan')}, {'created_at':102}, {'action':'HOLD'},
    {'policy':{'exploration':True}}, {'policy':{}},
])
def test_hold_stale_and_exploration_never_enter_browser(tmp_path, change):
    ledger=store(tmp_path); adapter=Adapter(); worker=AutoExecutor(ledger,adapter,clock=lambda:101)
    assert worker.process({**decision(),**change})['status']=='held'
    assert not adapter.calls
    ledger.close()


@pytest.mark.parametrize('field,value', [('relay_status','PENDING'),('balances_verified',False),('account_ref','b'),
    ('route_id',None),('asset_id','other'),('clicked',False),('observed_at',float('nan')),('position_after',None)])
def test_incomplete_receipt_never_books_a_position(tmp_path, field, value):
    ledger=store(tmp_path); intent,_=ledger.make_intent(decision(),101)
    evidence=fill(intent); evidence[field]=value
    result=AutoExecutor(ledger,Adapter(evidence),clock=lambda:101).process(decision())
    assert result['status']=='unknown' and ledger.holding('worm') is None
    ledger.close()


def test_preclick_block_can_accept_later_decision_and_shadow_cannot_fill(tmp_path):
    ledger=store(tmp_path); adapter=Adapter({'status':'blocked','clicked':False,'reason':'Fee cap'})
    worker=AutoExecutor(ledger,adapter,clock=lambda:101)
    assert worker.process(decision())['status']=='blocked'
    assert worker.process(decision('next'))['status']=='blocked'
    assert len(adapter.calls)==2
    ledger.close()
    path=tmp_path/'shadow'; path.mkdir(); ledger=store(path,mode='shadow'); adapter=Adapter()
    assert AutoExecutor(ledger,adapter,clock=lambda:101).process(decision())['status']=='unknown'
    assert adapter.calls[0][1] is False and ledger.holding('worm') is None
    ledger.close()


def test_daily_budget_and_cooldown(tmp_path):
    ledger=store(tmp_path,limits=ExecutionLimits(max_buys_per_day=1))
    worker=AutoExecutor(ledger,Adapter(),clock=lambda:101)
    worker.process(decision())
    worker.clock=lambda:102
    assert worker.process(decision('early',action='SELL'))['reason']=='Execution cooldown'
    risk=decision('risk',action='SELL'); risk['intent']['risk_exit']=True
    assert worker.process(risk)['status']=='filled'
    worker.clock=lambda:301
    assert worker.process(decision('entry',at=300))['reason']=='Daily entry budget reached'
    ledger.close()


@pytest.mark.parametrize('args', [{'buy_usd':'11'}, {'max_buy_usd':'20'}, {'buy_usd':'0'},
    {'buy_usd':'NaN'}, {'max_fee_usd':'Infinity'}, {'max_fee_usd':'2.01'}, {'max_fee_bps':True}, {'acknowledge_network_fee':'false'}])
def test_invalid_configuration_rejected(args):
    with pytest.raises(ValueError):ExecutionLimits(**args)


def test_two_dollar_fee_cap_preserves_the_percentage_limit_in_order_evidence(tmp_path):
    limits=ExecutionLimits(buy_usd='5',max_fee_usd='2',max_fee_bps=1000)
    ledger=store(tmp_path,limits=limits)
    intent,reason=ledger.make_intent(decision(),101)
    assert reason is None and intent['limits']['max_fee_usd']=='2'
    assert intent['limits']['max_fee_bps']==1000 and intent['amount_usd']=='5'
    ledger.close()


def test_paused_feed_newer_hold_and_previous_run_are_not_replayed():
    state={'status':'running','paused':False,'mode':'paper','market_mode':'fomo_trending',
           'market_fresh':True,'server_time':101,'run_id':'run'}
    hold=decision('hold',action='HOLD',at=101)
    assert current_decisions(state,[decision(),hold],102,accept_after=99)==[hold]
    for changed in ({'paused':True},{'market_fresh':False},{'server_time':50},{'run_id':'new'}):
        assert current_decisions({**state,**changed},[decision()],102,accept_after=99)==[]
    assert current_decisions(state,[decision()],102,accept_after=101)==[]


def test_stop_before_claim_and_account_config_gate(tmp_path):
    ledger=store(tmp_path); adapter=Adapter()
    assert AutoExecutor(ledger,adapter,enabled=lambda:False).process(decision())['status']=='held'
    assert ledger.status('one') is None
    ledger.close()
    account={'enabled':False,'account_ref':'a','session':'one','browser_directory':str(tmp_path),
             'profile':'test','user_id':'test-id','chain':'robinhood','chain_id':4663,
             'cash_wallet':'1'*32,'token_wallet':ADDRESS}
    config={'enabled':False,'source_url':'http://127.0.0.1:8140','accounts':{'worm':account},'limits':asdict(ExecutionLimits())}
    path=tmp_path/'config.json'; path.write_text(json.dumps(config))
    load_config(path)
    with pytest.raises(ValueError,match='disabled'):load_config(path,live=True)
    config.update(enabled=True); config['accounts']['worm']['enabled']=True
    path.write_text(json.dumps(config)); load_config(path,live=True)
    config['accounts']['adult']=deepcopy(account);path.write_text(json.dumps(config))
    with pytest.raises(ValueError,match='distinct'):load_config(path)
