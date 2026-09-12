from copy import deepcopy

import pytest

from bio_arena.challenge import ChallengeStore
from bio_arena.prediction_sandbox import PredictionSandbox
from bio_arena.voting import VoteSettings


def round_fixture(store,at,values):
    store.observe({'at':at,'source_at':at,'sequence':at,'run_id':'fixture','capital_flows':[],
                   'accounts':{b:{'equity':v,'alive':True} for b,v in zip(('worm','adult','larva'),values)}},VoteSettings(mode='paper_test').public())


@pytest.mark.parametrize('end,mode', [((90,100,100),'proportional_pool'),((90,90,100),'refund'),((100,100,100),'refund'),((100,100,90),'refund')])
def test_pool_conserves_points_idempotently_across_settlement_and_restart(tmp_path,end,mode):
    rounds=ChallengeStore(tmp_path/'rounds.sqlite');round_fixture(rounds,3600,(100,100,100))
    opening=rounds.get('paper:fixture:3600');path=tmp_path/'pool.sqlite'
    market=PredictionSandbox(path);market.open(opening)
    for player in ('a','b','c'):market.grant('grant:'+player,player,100)
    market.stake('s1',opening['id'],'a','worm',11,3601)
    market.stake('s2',opening['id'],'b','adult',33,3601)
    market.stake('s3',opening['id'],'c','worm',13,3601)
    market.stake('s3',opening['id'],'c','worm',13,3602)
    assert sum(market.balance(p) for p in ('a','b','c'))==243
    with pytest.raises(ValueError,match='window closed'):market.stake('late',opening['id'],'a','worm',1,4500)
    with pytest.raises(ValueError,match='frozen'):
        altered=deepcopy(opening);altered['rules']['participants'].append('future_bio');market.open(altered)
    round_fixture(rounds,7200,end);closed=rounds.get(opening['id']);result=market.settle(closed)
    assert result['mode']==mode and sum(result['payouts'].values())==57
    assert sum(market.balance(p) for p in ('a','b','c'))==300
    market.close();market=PredictionSandbox(path)
    assert market.settle(closed)==result
    assert sum(market.balance(p) for p in ('a','b','c'))==300
    changed=deepcopy(closed);changed['reason']='changed'
    with pytest.raises(ValueError,match='immutable'):market.settle(changed)
    market.close();rounds.close()


def test_void_refund_and_insufficient_balance_cannot_create_points():
    rounds=ChallengeStore(':memory:');round_fixture(rounds,3600,(100,100,100));opening=rounds.get('paper:fixture:3600')
    market=PredictionSandbox(':memory:');market.open(opening);market.grant('grant','a',20)
    with pytest.raises(ValueError,match='Insufficient'):market.stake('too-large',opening['id'],'a','worm',21,3601)
    assert market.balance('a')==20
    market.stake('ok',opening['id'],'a','worm',20,3601)
    rounds.invalidate('Missing fresh closing snapshot');result=market.settle(rounds.get(opening['id']))
    assert result['mode']=='refund' and market.balance('a')==20
    market.close();rounds.close()
