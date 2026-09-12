from copy import deepcopy
from pathlib import Path
import pytest,yaml
from bio_arena.trading import PaperBroker,FomoAdapter

@pytest.fixture
def config():return yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/arena.yaml').read_text())

def intent(id='one',bio='worm',action='BUY',score=1,at=100):
    return dict(id=id,bio_id=bio,created_at=at,action=action,score=score,reason='test')

def quote(at=101,price=100):
    return dict(id=str(at),received_at=at,bid=price,ask=price,price=price)

def test_fee_slippage_cash_conservation_and_independence(config):
    broker=PaperBroker(config)
    before=deepcopy(broker.accounts['adult'])
    fill=broker.execute(intent(),quote())
    a=broker.accounts['worm']
    assert fill['status']=='filled'
    assert fill['fill_price']==pytest.approx(100.05)
    assert a.cash+a.quantity*fill['fill_price']+a.fees==pytest.approx(a.initial_cash)
    assert broker.accounts['adult']==before
    assert a.equity(100)<a.initial_cash

def test_future_quote_and_idempotency(config):
    b=PaperBroker(config)
    with pytest.raises(ValueError):b.execute(intent(),quote(99))
    b.execute(intent(),quote())
    original=deepcopy(b.accounts['worm'])
    assert b.execute(intent(),quote(102))['status']=='duplicate'
    assert b.accounts['worm']==original

def test_sell_cannot_short_and_buy_cannot_overspend(config):
    config['cooldown_seconds']=0
    b=PaperBroker(config)
    assert b.execute(intent(action='SELL',score=-1),quote())['status']=='held'
    for i in range(100):b.execute(intent(str(i),at=100+i),quote(at=101+i))
    assert b.accounts['worm'].cash>=0
    for i in range(100):b.execute(intent('sell'+str(i),action='SELL',score=-1,at=1000+i),quote(at=1001+i))
    assert b.accounts['worm'].quantity>=0

def test_stop_line_liquidates_even_on_hold_and_during_cooldown(config):
    b=PaperBroker(config);a=b.accounts['worm']
    a.cash=0;a.quantity=100;a.last_trade_ts=100
    fill=b.execute(intent(action='HOLD',score=0),quote(price=19))
    assert not a.alive
    assert a.quantity==0
    assert fill['action']=='SELL' and fill['decision_action']=='HOLD'
    assert fill['status']=='filled'

def test_cooldown_retains_neural_action(config):
    b=PaperBroker(config);b.execute(intent(),quote())
    fill=b.execute(intent('two',action='SELL',at=101),quote(102))
    assert fill['status']=='held' and fill['decision_action']=='SELL'

def test_live_adapter_cannot_submit():
    with pytest.raises(NotImplementedError):FomoAdapter().execute({}, {})
