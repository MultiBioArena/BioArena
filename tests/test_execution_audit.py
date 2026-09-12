"""Offline signal coverage; fixture receipts are never evidence of funded trading."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bio_arena.auto_execution import AutoExecutor, ExecutionLimits, ExecutionStore
from bio_arena.execution_audit import PolicyExecutionAudit, require_execution_check
from bio_arena.execution_trial import ExecutionTrial
from test_execution_trial import Adapter, decision


def test_hold_exploration_and_rejected_quote_are_observed_without_claiming_a_pass(tmp_path):
    path=tmp_path/'fixture.sqlite'
    store=ExecutionStore(path,'live',{'adult':'fixture'},ExecutionLimits())
    trial=ExecutionTrial(store,'policy','adult',99)
    audit=PolicyExecutionAudit(store,trial.id)
    class Blocked:
        calls=0
        def execute(self,*_,**kwargs):
            self.calls+=1
            return {'status':'blocked','clicked':False,'reason':'Quoted fees exceed configured limits'}
    adapter=Blocked();executor=AutoExecutor(store,adapter,clock=lambda:101,trial_id=trial.id)
    hold=decision('hold','HOLD')
    explore=decision('explore','BUY');explore['policy']['exploration']=True
    for d in [hold,explore,decision('qualified','BUY')]:
        audit.process(d,executor,trial,101)
    assert adapter.calls==1 and not trial.state(3700)['complete']
    summary=audit.summary()['adult']
    assert summary['actions']=={'HOLD':1,'BUY':2}
    assert summary['outcomes']=={'filtered':1,'held':1,'blocked':1}
    assert summary['reasons']['Paper exploration is excluded from live execution']==1
    store.close()
    store=ExecutionStore(path,'live',{'adult':'fixture'},ExecutionLimits())
    assert PolicyExecutionAudit(store,'policy').summary()['adult']==summary
    store.close()


def test_policy_sell_must_match_actual_executor_holding(tmp_path):
    store=ExecutionStore(tmp_path/'fixture.sqlite','live',{'adult':'fixture'},ExecutionLimits())
    trial=ExecutionTrial(store,'policy','adult',99);audit=PolicyExecutionAudit(store,trial.id)
    adapter=Adapter();executor=AutoExecutor(store,adapter,clock=lambda:101,trial_id=trial.id)
    audit.process(decision('buy','BUY'),executor,trial,101)
    executor.clock=lambda:301
    wrong=decision('wrong','SELL',300)
    wrong['asset']['asset_id']='robinhood:0x'+'2'*40
    audit.process(wrong,executor,trial,301)
    assert adapter.clicks==1 and store.holding('adult')
    audit.process(decision('sell','SELL',300),executor,trial,301)
    assert trial.state(302)['complete'] and adapter.clicks==2
    intents=[json.loads(r[0]) for r in store.db.execute('SELECT intent FROM orders')]
    assert all(i['source_kind']=='bio_policy' for i in intents)
    assert intents[1]['quantity_raw']=='2000'
    store.close()


def test_second_test_requires_first_test_on_same_bio_and_live_journal(tmp_path):
    store=ExecutionStore(tmp_path/'fixture.sqlite','live',{'adult':'a','worm':'b'},ExecutionLimits())
    with pytest.raises(ValueError,match='both real fills'):
        require_execution_check(store,'execution','adult')
    trial=ExecutionTrial(store,'execution','adult',99,context={'source_kind':'operator_execution_check'})
    executor=AutoExecutor(store,Adapter(),clock=lambda:101,trial_id=trial.id,source_kind='operator_execution_check')
    executor.process(decision('buy','BUY'))
    with pytest.raises(ValueError):require_execution_check(store,'execution','adult')
    executor.clock=lambda:301;executor.process(decision('sell','SELL',300));assert trial.state(302)['complete']
    require_execution_check(store,'execution','adult')
    with pytest.raises(ValueError):require_execution_check(store,'execution','worm')
    store.close()


@pytest.mark.parametrize('bio',['worm','adult','larva'])
def test_actual_policy_emits_buy_and_sell_and_routes_exact_real_ledger_quantity(tmp_path,monkeypatch,bio):
    from bio_arena.meme_arena import MemecoinArena
    from bio_arena.learning import ReadoutLearner
    from bio_arena.portfolio import PortfolioBroker
    from test_memecoin import quote, intent
    settings=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/fomo.yaml').read_text())['memecoin']
    arena=object.__new__(MemecoinArena)
    arena.settings=settings
    arena.broker=PortfolioBroker(10000,settings,.2)
    arena.learners={bio:ReadoutLearner(bio,42,settings['learning'])}
    now=[1000.]
    monkeypatch.setattr('bio_arena.meme_arena.time.time',lambda:now[0])
    q=quote(n=int('1'*40,16),chain='robinhood',now=1000)
    q['change_5m_pct']=10
    arena.market=SimpleNamespace(entry_problem=lambda _:None,histories={q['asset_id']:[q]})
    features={'history_samples':10,'return_bps':100,'volume':.8,'volatility':.2}
    neural={'score':.9,'readout_rates':{'buy':50,'sell':1}}
    store=ExecutionStore(tmp_path/'fixture.sqlite','live',{bio:'fixture'},ExecutionLimits())
    trial=ExecutionTrial(store,'policy',bio,999)
    audit=PolicyExecutionAudit(store,trial.id);adapter=Adapter()
    executor=AutoExecutor(store,adapter,clock=lambda:now[0]+1,trial_id=trial.id)
    for action in ('BUY','SELL'):
        chosen=arena.choose(bio,[arena.evaluate(bio,q,features,neural)])
        assert chosen['action']==action and chosen['exploration'] is False
        signal=decision(bio+action,chosen['action'],now[0],bio)
        signal.update(reason=chosen['reason'],policy={'exploration':chosen['exploration'],'model_version':chosen['model_version']})
        assert audit.process(signal,executor,trial,now[0]+1)['status']=='filled'
        if action=='BUY':
            assert arena.broker.execute(intent(q,bio+'paper',bio=bio),q,1000)['status']=='filled'
            now[0]=1300
            q={**q,'received_at':1300,'change_5m_pct':-10}
            neural={'score':-.9,'readout_rates':{'buy':1,'sell':50}}
    assert trial.state(1302)['complete'] and adapter.clicks==2
    rows=[json.loads(r[0]) for r in store.db.execute('SELECT intent FROM orders')]
    assert rows[1]['quantity_raw']=='2000'
    assert arena.broker.accounts[bio].positions[q['asset_id']].quantity!=2
    store.close()
