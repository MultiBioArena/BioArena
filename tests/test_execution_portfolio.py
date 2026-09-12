import json
import sqlite3
from dataclasses import asdict

import pytest
import httpx

from bio_arena.auto_execution import AutoExecutor, ExecutionLimits, ExecutionStore
from bio_arena.execution_exits import ExitSettings, LiveExitManager
from bio_arena.execution_trial import PortfolioTrial


def decision(key, action='BUY', index=1, at=100):
    address='0x'+str(index)*40
    asset={'chain':'robinhood','address':address,'asset_id':'robinhood:'+address}
    return {'id':key,'bio_id':'adult','created_at':at,'action':action,'asset':asset,
        'reason':'Fixture Bio policy','policy':{'exploration':False},
        'intent':{'action':action,'asset_id':asset['asset_id']}}


class Browser:
    def __init__(self):self.calls=[];self.block=False;self.unknown=False
    def execute(self,intent,limits,live):
        self.calls.append(intent)
        if self.block:return {'status':'blocked','clicked':False,'reason':'Quoted fees exceed configured limits'}
        if self.unknown:return {'status':'unknown','clicked':True}
        buy=intent['action']=='BUY'
        return {'status':'filled','clicked':True,'account_ref':intent['account_ref'],'asset_id':intent['asset_id'],
            'action':intent['action'],'relay_status':'SUCCESS','route_id':intent['id'],
            'observed_at':intent['created_at']+1,'balances_verified':True,'cash_delta_usd':-2 if buy else 1.8,
            'position_after':{'asset_id':intent['asset_id'],'raw_quantity':'2000000','decimals':6} if buy else None}


class NoNetwork:
    def get(self,url):raise AssertionError('Fixture unexpectedly requested the network')


def setup(tmp_path):
    limits=ExecutionLimits(max_positions=2,sell_cooldown_seconds=0,allow_exploration=True)
    store=ExecutionStore(tmp_path/'ledger.sqlite','live',{'adult':'a'},limits)
    trial=PortfolioTrial(store,'two','adult',99,3600)
    browser=Browser();clock=[101]
    worker=AutoExecutor(store,browser,clock=lambda:clock[0],trial_id=trial.id)
    return store,trial,browser,worker,clock


def state(positions,now,price=1):
    return {'status':'running','server_time':now,'assets':[{'asset_id':p['asset_id'],
        'quote':{'asset_id':p['asset_id'],'id':'quote-'+str(now),'price':price,'received_at':now}} for p in positions]}


def test_two_positions_survive_restart_and_selling_one_preserves_the_other(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path)
    assert worker.process(decision('a'))['status']=='filled'
    clock[0]=300
    assert worker.process(decision('b',index=2,at=300))['status']=='filled'
    assert len(store.holdings('adult'))==2
    assert not trial.accepts(decision('c',index=3,at=300),300)
    assert worker.process(decision('c',index=3,at=300))['status']=='held'
    store.close()
    store=ExecutionStore(tmp_path/'ledger.sqlite','live',{'adult':'a'},ExecutionLimits(max_positions=2,sell_cooldown_seconds=0,allow_exploration=True))
    trial=PortfolioTrial(store,'two','adult',301,3600)
    worker=AutoExecutor(store,browser,clock=lambda:302,trial_id=trial.id)
    assert worker.process(decision('exit-b','SELL',index=2,at=302))['status']=='filled'
    assert [p['buy_id'] for p in store.holdings('adult')]==['a']
    assert not trial.state(303)['complete']
    worker.clock=lambda:304
    assert worker.process(decision('exit-a','SELL',at=304))['status']=='filled'
    result=trial.state(305)
    assert result['complete'] and result['completed_round_trips']==2 and result['real_orders_verified']==4
    assert result['cash_change_usd']==pytest.approx(-0.4)
    assert not store.holdings('adult')
    store.close()


def test_latched_sell_survives_paper_hold_fee_block_and_restart(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path);worker.process(decision('a'))
    manager=LiveExitManager(store,ExitSettings(),NoNetwork())
    now=230;quote=state(store.holdings('adult'),now)
    sell=decision('paper-sell','SELL',at=now)
    planned=manager.review('adult',quote,[sell],now)
    browser.block=True;clock[0]=now
    assert worker.process(planned[0])['status']=='blocked'
    assert manager.review('adult',quote,[],now+1)==[]
    manager=LiveExitManager(store,ExitSettings(),NoNetwork())
    now+=31
    planned=manager.review('adult',state(store.holdings('adult'),now),[],now)
    assert planned[0]['exit_evidence']['source_decision_id']=='paper-sell'
    browser.block=False;clock[0]=now
    assert worker.process(planned[0])['status']=='filled'
    assert not store.holdings('adult')
    store.close()


def test_own_stop_works_without_paper_position_or_sell_and_unknown_never_retries(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path);worker.process(decision('a'))
    manager=LiveExitManager(store,ExitSettings(),NoNetwork())
    planned=manager.review('adult',state(store.holdings('adult'),105,price=.7),[],105)
    assert planned[0]['reason']=='Real position drawdown limit reached'
    assert planned[0]['exit_evidence']['return_fraction']==pytest.approx(-.3)
    clock[0]=105;browser.unknown=True
    assert worker.process(planned[0])['status']=='unknown'
    assert manager.review('adult',{},[],500)==[]
    assert trial.state(500)['phase']=='review_required'
    assert store.holdings('adult')
    store.close()


def test_entry_deadline_keeps_exit_management_running_until_verified_closed(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path);worker.process(decision('a'))
    assert trial.state(4000)['phase']=='closing_positions'
    assert not trial.accepts(decision('late',index=2,at=4000),4000)
    manager=LiveExitManager(store,ExitSettings(),NoNetwork())
    planned=manager.review('adult',state(store.holdings('adult'),4000),[],4000,close_all=True)
    assert trial.accepts(planned[0],4000)
    clock[0]=4000;worker.process(planned[0])
    result=trial.state(4001)
    assert result['complete'] and result['completed_round_trips']==1 and not result['entry_target_reached']
    store.close()


def test_legacy_holding_migration_preserves_exact_quantity(tmp_path):
    path=tmp_path/'old.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE holdings(account TEXT PRIMARY KEY,asset TEXT,raw_quantity TEXT,decimals INTEGER,opened_at REAL,buy_id TEXT)')
        db.execute('INSERT INTO holdings VALUES (?,?,?,?,?,?)',('a',decision('a')['asset']['asset_id'],'123456789123456789',18,100,'entry'))
    store=ExecutionStore(path,'live',{'adult':'a'},ExecutionLimits(max_positions=2))
    assert store.holding('adult')['raw_quantity']=='123456789123456789'
    assert [r[1] for r in store.db.execute('PRAGMA table_info(holdings)') if r[5]]==['account','asset']
    store.close()


def test_exploration_allowed_only_by_explicit_limit_and_sell_skips_entry_cooldown(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path)
    d=decision('explore');d['policy']['exploration']=True
    assert worker.process(d)['status']=='filled'
    clock[0]=102
    assert worker.process(decision('exit','SELL',at=102))['status']=='filled'
    store.close()


def test_held_token_is_refreshed_when_absent_from_paper_and_trending(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path);worker.process(decision('a'))
    address=decision('a')['asset']['address'];urls=[]
    class Market:
        def get(self,url):
            urls.append(url)
            return httpx.Response(200,request=httpx.Request('GET',url),json=[{
                'chainId':'robinhood','baseToken':{'address':address},'pairAddress':'fixture-pool',
                'priceUsd':'.7','liquidity':{'usd':100000}}])
    manager=LiveExitManager(store,ExitSettings(),Market())
    planned=manager.review('adult',{},[],110)
    assert planned[0]['reason']=='Real position drawdown limit reached'
    assert urls==['https://api.dexscreener.com/tokens/v1/robinhood/'+address]
    assert planned[0]['exit_evidence']['reference_quote']['asset_id']==decision('a')['asset']['asset_id']
    store.close()


def test_time_exit_can_prepare_fomo_quote_when_reference_feed_is_unavailable(tmp_path):
    store,trial,browser,worker,clock=setup(tmp_path);worker.process(decision('a'))
    class Down:
        def get(self,url):raise httpx.ReadTimeout('Fixture network outage')
    manager=LiveExitManager(store,ExitSettings(),Down())
    planned=manager.review('adult',{},[],2000)
    assert planned[0]['reason']=='Maximum real holding time reached'
    assert planned[0]['exit_evidence']['reference_quote'] is None
    assert planned[0]['intent']['risk_exit'] is True
    store.close()


@pytest.mark.parametrize('args',[{'max_positions':3},{'max_positions':True},{'max_slippage_bps':3001},{'allow_exploration':'true'},{'sell_cooldown_seconds':-1}])
def test_invalid_portfolio_limits(args):
    with pytest.raises(ValueError):ExecutionLimits(**args)
