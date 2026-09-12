from copy import deepcopy
import hashlib
from pathlib import Path
import random
import yaml

from bio_arena.comparison import experiment

ROOT=Path(__file__).resolve().parents[1]


class FakeBrain:
    def __init__(self,root,key,config):pass
    def reset(self):self.rng=random.Random(self.seed)
    def step(self,features):
        score=self.rng.uniform(.2,.9)
        return {'score':score,'readout_rates':{'buy':40,'sell':5},'counts_sha256':hashlib.sha256(str(score).encode()).hexdigest()}


def tape():
    config=yaml.safe_load((ROOT/'configs/fomo.yaml').read_text());config['competitors']=['worm']
    settings=config['memecoin'];settings.update(bio_warmup_observations=0,trade_cooldown_seconds=0,minimum_hold_seconds=0)
    settings['learning'].update(label_horizon_seconds=2,label_grace_seconds=6,minimum_training_samples=2,validation_samples=2)
    quote={'asset_id':'base:0x'+'a'*40,'chain':'base','address':'0x'+'a'*40,'symbol':'TEST','price':10,
           'id':'q','pair_address':'pool','liquidity_usd':1e8,'volume_5m_usd':1e6,'sells_5m':100,'change_5m_pct':10}
    features={'approach':.7,'avoid':.1,'volume':.5,'volatility':.1,'return_bps':10,'history_samples':10}
    observations=[];decisions=[];quotes=[]
    for i in range(12):
        t=100+i*4;q={**quote,'id':f'q:{i}','received_at':t,'price':10+i*.1}
        quotes += [q,{**q,'received_at':t+2,'id':f'fill:{i}'}]
        observations.append({'id':str(i),'bio_id':'worm','evaluated_at':t+1,'input_quote':q,'features':features,
                             'evaluation':{'round_trip_cost_bps':100,'entry_problem':None}})
        decisions.append({'id':str(i),'bio_id':'worm','at':t+1.5,'slate':[str(i)]})
    return {'config':config,'quotes':quotes,'observations':observations,'decisions':decisions,'last_at':146}


def test_causal_delayed_fills_same_seed_reproducible_cash_baseline():
    data=tape();before=deepcopy(data)
    a=experiment(ROOT,data,11,brain_factory=FakeBrain);b=experiment(ROOT,data,11,brain_factory=FakeBrain)
    assert a==b and data==before
    assert a['fills'] and all(f['timestamp']>f['decision_at'] for f in a['fills'])
    assert a['results']['cash']['worm']['return_pct']==0
    assert a['results']['cash']['worm']['trades']==0
    assert a['learners']['worm']['updates']>0
    assert a['spike_tape_hashes']!=experiment(ROOT,data,12,brain_factory=FakeBrain)['spike_tape_hashes']


def test_future_price_change_cannot_modify_prior_fills():
    data=tape();original=experiment(ROOT,data,11,brain_factory=FakeBrain)
    for q in data['quotes']:
        if q['received_at']>=130:q['price']*=2
    changed=experiment(ROOT,data,11,brain_factory=FakeBrain)
    assert [f for f in original['fills'] if f['timestamp']<130]==[f for f in changed['fills'] if f['timestamp']<130]
