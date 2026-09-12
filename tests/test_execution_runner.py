"""Run the CLI loop with an isolated journal, synthetic feed and no browser/network."""
import importlib.util
import json
from pathlib import Path
import pytest


@pytest.mark.parametrize('target',['worm','adult','larva'])
@pytest.mark.parametrize('exploration',[False,True])
def test_operator_trial_routes_only_one_bio_and_restart_cannot_repeat(tmp_path, monkeypatch, capsys,target,exploration):
    path = Path(__file__).resolve().parents[1] / 'scripts/run_fomo_executor.py'
    spec = importlib.util.spec_from_file_location('trial_runner', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    accounts = {}
    for index, bio in enumerate(('adult', 'worm','larva'), 1):
        browser = tmp_path / bio
        browser.mkdir()
        accounts[bio] = {'enabled': False, 'account_ref': bio, 'session': bio,
            'browser_directory': str(browser), 'profile': bio, 'user_id': bio,
            'chain': 'robinhood', 'chain_id': 4663,
            'cash_wallet': str(index)*32, 'token_wallet': '0x'+str(index)*40}
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'enabled': False, 'source_url': 'http://localhost', 'accounts': accounts}))
    now = [100.0]
    calls = []
    token = '0x'+'3'*40
    asset = {'asset_id': 'robinhood:'+token, 'chain': 'robinhood', 'address': token}

    class Response:
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): pass
        def json(self): return self.payload

    class Feed:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, url, **_):
            now[0] += 1
            if url == '/api/state':
                return Response({'run_id': 'fixture', 'status': 'running', 'paused': False,
                    'mode': 'paper', 'market_mode': 'fomo_trending', 'market_fresh': True,
                    'server_time': now[0]})
            action = 'BUY' if not calls else 'SELL'
            return Response([{'id': bio+'-'+action, 'bio_id': bio, 'run_id': 'fixture',
                'created_at': now[0], 'action': action, 'asset': asset,
                'intent': {'action': action, 'asset_id': asset['asset_id']},
                'reason': 'Synthetic CLI fixture', 'policy': {'exploration': exploration}}
                for bio in ('worm', 'adult','larva')])

    class Browser:
        def __init__(self, *_): pass
        def execute(self, intent, limits, *, live=False):
            assert live and intent['bio_id'] == target
            calls.append(intent)
            now[0] += 1
            buy = intent['action'] == 'BUY'
            return {'status': 'filled', 'clicked': True, 'account_ref': intent['account_ref'],
                'asset_id': asset['asset_id'], 'action': intent['action'], 'relay_status': 'SUCCESS',
                'route_id': intent['id'], 'observed_at': now[0], 'balances_verified': True,
                'cash_delta_usd': -2 if buy else 1.8,
                'position_after': {'asset_id': asset['asset_id'], 'raw_quantity': '2000', 'decimals': 3} if buy else None}

    monkeypatch.setattr(runner.httpx, 'Client', Feed)
    monkeypatch.setattr(runner, 'FomoBrowserExecutor', Browser)
    monkeypatch.setattr(runner.time, 'time', lambda: now[0])
    monkeypatch.setattr(runner.time, 'sleep', lambda _: now.__setitem__(0, now[0]+125))
    monkeypatch.setattr(runner.signal, 'signal', lambda *_: None)
    args = ['--config', str(config), '--start-live-trial', target]
    code=runner.main(args)
    report = json.loads((tmp_path/'execution/live-status.json').read_text())
    if exploration:
        assert code==1 and not report['trial']['complete'] and report['trial']['phase']=='expired'
        assert not calls and report['counts']=={}
        assert report['policy_audit'][target]['actions']=={'BUY':1}
        assert report['policy_audit'][target]['reasons']=={'Paper exploration is excluded from live execution':1}
        return
    assert code==0
    assert report['trial']['complete'] and report['counts'] == {'filled': 2}
    assert report['process_running'] is False
    assert [i['action'] for i in calls] == ['BUY', 'SELL']
    assert all(i['trial_id'] == 'first-live-cycle' for i in calls)
    assert report['policy_audit'][target]['outcomes']=={'filled':2}
    assert all(row['observed']==0 for bio,row in report['policy_audit'].items() if bio!=target)
    runner.main(args)
    assert len(calls) == 2
    assert not json.loads(config.read_text())['enabled']
    assert all(not a['enabled'] for a in json.loads(config.read_text())['accounts'].values())
    assert len(capsys.readouterr().out.strip().splitlines()) == 4


def test_managed_cli_buys_two_then_exits_both_without_any_paper_sell(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('managed_runner',Path(__file__).resolve().parents[1]/'scripts/run_fomo_executor.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    browser_dir=tmp_path/'browser';browser_dir.mkdir()
    account={'enabled':False,'account_ref':'a','session':'fixture','browser_directory':str(browser_dir),
        'profile':'fixture','user_id':'fixture','cash_wallet':'1'*32,'token_wallet':'0x'+'2'*40}
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'enabled':False,'source_url':'http://localhost','accounts':{'adult':account},
        'limits':{'max_positions':2,'sell_cooldown_seconds':0,'allow_exploration':True}}))
    assets=[{'chain':'robinhood','address':'0x'+str(i)*40,'asset_id':'robinhood:0x'+str(i)*40} for i in (3,4)]
    now=[100.];calls=[];max_held=[0];held=set()
    class Response:
        def __init__(self,value):self.value=value
        def raise_for_status(self):pass
        def json(self):return self.value
    class Feed:
        def __init__(self,**_):pass
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def get(self,url,**_):
            now[0]+=1
            if url=='/api/state':
                return Response({'run_id':'fixture','status':'running','paused':False,'mode':'paper',
                    'market_mode':'fomo_trending','market_fresh':True,'server_time':now[0],'bios':[],
                    'assets':[{'asset_id':a['asset_id'],'quote':{**a,'id':'q','received_at':now[0],
                        'price':.7 if len(calls)>=2 else 1}} for a in assets]})
            assert url=='/api/decisions'
            action='BUY' if len(calls)<2 else 'HOLD';a=assets[min(len(calls),1)]
            return Response([{'id':'d-'+str(len(calls)),'run_id':'fixture','bio_id':'adult','created_at':now[0],
                'action':action,'asset':a,'reason':'Synthetic neural entry','policy':{'exploration':True},
                'intent':{'action':action,'asset_id':a['asset_id']}}])
    class Browser:
        def __init__(self,*_):pass
        def execute(self,intent,limits,live):
            assert live;calls.append(intent);buy=intent['action']=='BUY'
            if buy:held.add(intent['asset_id'])
            else:held.remove(intent['asset_id'])
            max_held[0]=max(max_held[0],len(held))
            return {'status':'filled','clicked':True,'account_ref':'a','asset_id':intent['asset_id'],
                'action':intent['action'],'route_id':intent['id'],'relay_status':'SUCCESS','balances_verified':True,
                'observed_at':now[0]+.1,'cash_delta_usd':-2 if buy else 1.4,
                'position_after':{'asset_id':intent['asset_id'],'raw_quantity':'2000000','decimals':6} if buy else None}
    monkeypatch.setattr(runner.httpx,'Client',Feed);monkeypatch.setattr(runner,'FomoBrowserExecutor',Browser)
    monkeypatch.setattr(runner.time,'time',lambda:now[0]);monkeypatch.setattr(runner.time,'sleep',lambda _:now.__setitem__(0,now[0]+125))
    monkeypatch.setattr(runner.signal,'signal',lambda *_:None)
    args=['--config',str(config),'--start-live-trial','adult','--managed-portfolio']
    assert runner.main(args)==0
    assert [i['action'] for i in calls]==['BUY','BUY','SELL','SELL']
    assert max_held[0]==2 and not held
    assert all(i['reason']=='Real position drawdown limit reached' for i in calls[2:])
    report=json.loads((tmp_path/'execution/live-status.json').read_text())
    assert report['trial']['completed_round_trips']==2 and report['trial']['complete']
    assert runner.main(args)==0 and len(calls)==4
