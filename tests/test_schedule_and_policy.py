from pathlib import Path
from copy import deepcopy
import json
import shutil
import pytest
import yaml
from bio_arena.scheduling import DecisionSchedule
from bio_arena.policy import OpportunityPolicy
from bio_arena.trading import PaperBroker
from bio_arena.arena import Arena

ROOT=Path(__file__).resolve().parents[1]
KEYS=['worm','adult','larva']

def config():return yaml.safe_load((ROOT/'configs/arena.yaml').read_text())
def quote(t,price=100):return dict(id=str(t),received_at=t,price=price,bid=price,ask=price)
def neural(action='BUY',score=.8):return dict(action=action,score=score,readout_rates={'buy':20,'sell':5})

def test_schedule_independent_random_streams_and_recovery_without_burst():
    a=DecisionSchedule(config(),KEYS);b=DecisionSchedule(config(),KEYS);a.start(100);b.start(100)
    assert a.ready(100,KEYS)=='worm'
    first=a.dispatch('worm',100);assert first==b.dispatch('worm',100)
    a.completed(101)
    assert a.ready(104,KEYS) is None
    assert a.ready(107,KEYS)=='adult'
    for t in range(107,507,20):a.dispatch('adult',t)
    assert a.dispatch('worm',121)==b.dispatch('worm',121)
    a.completed(500)
    assert a.ready(503,KEYS) is None
    key=a.ready(504,KEYS);assert key is not None
    timing=a.dispatch(key,504);assert 17<=timing['interval_seconds']<=23
    a.completed(505)
    assert a.ready(508,KEYS) is None
    assert a.next_at[key]>504

def test_policy_requires_context_confirmation_cost_room_and_exposure_need():
    c=config();policy=OpportunityPolicy(c);account=PaperBroker(c).accounts['worm']
    for i in range(5):assert policy.decide(neural(),quote(100+i*20,100+i*.2),account)['action']=='HOLD'
    decision=policy.decide(neural(),quote(200,101),account)
    assert decision['action']=='BUY' and decision['target_position_fraction']==pytest.approx(.48)
    account.quantity=48;account.cash=5200
    assert policy.decide(neural(),quote(220),account)['action']=='HOLD'
    flat=OpportunityPolicy(c);empty=PaperBroker(c).accounts['worm']
    for i in range(10):assert flat.decide(neural(),quote(100+i*20,100+i*.001),empty)['action']=='HOLD'
    assert flat.decide(neural('SELL',-.8),quote(320),empty)['action']=='HOLD'

def test_weak_or_alternating_neural_signals_do_not_force_trades():
    p=OpportunityPolicy(config());a=PaperBroker(config()).accounts['worm']
    for i in range(12):
        signal=neural('BUY',.8) if i%2 else neural('SELL',-.8)
        assert p.decide(signal,quote(100+i*20,100+i),a)['action']=='HOLD'
    assert p.decide(neural('BUY',.15),quote(400,120),a)['action']=='HOLD'

def test_target_rebalance_and_delayed_reward_include_costs():
    c=config();broker=PaperBroker(c);a=broker.accounts['worm'];p=OpportunityPolicy(c)
    policy={'action':'BUY','target_position_fraction':.1}
    p.remember('first','worm',policy,{},neural(),a,quote(100))
    fill=broker.execute(dict(id='first',bio_id='worm',action='BUY',score=.8,reason='test',created_at=100,target_position_fraction=.1),quote(101))
    assert fill['notional']==pytest.approx(1000.5)
    outcome=p.observe(a,quote(120))
    assert outcome['decision_id']=='first'
    assert outcome['net_return_bps']==pytest.approx((a.equity(100)/10000-1)*10000)
    assert outcome['net_return_bps']<0 and outcome['reward_bps']<outcome['net_return_bps']
    assert p.observe(a,quote(140)) is None
    assert p.samples==1

@pytest.mark.requires_data
def test_history_filters_and_pages_without_activity_payload(tmp_path):
    shutil.copytree(ROOT/'configs',tmp_path/'configs')
    for key in KEYS:
        target=tmp_path/'data/processed'/key;target.mkdir(parents=True)
        for name in ['manifest.json','visual.json']:shutil.copy(ROOT/'data/processed'/key/name,target/name)
    arena=Arena(tmp_path)
    try:
        for i,key in enumerate(KEYS*4,1):
            record=dict(id=str(i),bio_id=key,sequence=(i+2)//3,created_at=i,action='HOLD',score=0,spikes=5,fill={'status':'held'},neural_activity='large')
            arena.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',(str(i),i,key,i,json.dumps(record)))
        arena.sequence=12
        first=arena.history('worm',2);second=arena.history('worm',2,first['next_before'])
        assert [x['event_sequence'] for x in first['items']]==[10,7]
        assert [x['event_sequence'] for x in second['items']]==[4,1]
        assert second['next_before'] is None
        assert all(x['bio_id']=='worm' and 'neural_activity' not in x for x in first['items'])
    finally:arena.db.close();arena.market_file.close()
