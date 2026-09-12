from dataclasses import asdict
import json

from bio_arena.auto_execution import ExecutionLimits, ExecutionStore
from bio_arena.execution_telemetry import public_snapshot


ASSET = 'robinhood:0x'+'1'*40


def fixture(tmp_path):
    store = ExecutionStore(tmp_path/'live.sqlite', 'live', {'adult':'private-account'}, ExecutionLimits())
    report = {'mode':'live','process_running':True,'live_enabled':True,'updated_at':100,
        'accounts':{'adult':{'private_profile':'secret-profile'}}, 'limits':asdict(store.limits),
        'trial':{'bio_id':'adult','phase':'waiting_buy','complete':False,'deadline':3700,'trial_id':'secret-trial'},
        'error':None,'last':{'evidence':{'authorization':'secret-token','wallet':'secret-wallet'}}}
    (tmp_path/'live-status.json').write_text(json.dumps(report))
    return store, report


def buy(store, filled=True):
    intent = {'id':'secret-order','bio_id':'adult','account_ref':'private-account',
        'created_at':100,'action':'BUY','asset_id':ASSET,'amount_usd':'2'}
    store.claim(intent,100)
    if filled:
        store.finish(intent, {'status':'filled','clicked':True,'asset_id':ASSET,'action':'BUY',
            'account_ref':'private-account','route_id':'secret-route','relay_status':'SUCCESS',
            'balances_verified':True,'observed_at':101,'cash_delta_usd':-2,
            'quote':{'fee_usd':0.02,'input_usd':2,'wallet':'secret-wallet'},
            'position_after':{'asset_id':ASSET,'raw_quantity':'2000','decimals':3}})


def test_public_projection_is_read_only_and_excludes_private_identity(tmp_path):
    store,_ = fixture(tmp_path);buy(store)
    result = public_snapshot(tmp_path,102)
    assert result['available'] and result['running'] and result['fresh']
    fly = next(b for b in result['bios'] if b['bio_id']=='adult')
    assert fly['selected'] and fly['holding']['quantity_raw']=='2000' and fly['verified_fills']==1
    assert result['orders'][0]['cash_delta_usd']==-2 and result['orders'][0]['estimated_fee_pct']==1
    assert not result['trial']['complete']
    assert 'secret' not in json.dumps(result) and 'private-account' not in json.dumps(result)
    assert store.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1
    store.close()


def test_two_holdings_and_absolute_only_fees_are_reported_without_private_fields(tmp_path):
    store,report=fixture(tmp_path);buy(store)
    second='base:0x'+'2'*40
    with store.db:
        store.db.execute('INSERT INTO holdings VALUES (?,?,?,?,?,?)',('private-account',second,'42',6,102,'private-second'))
    report['limits'].update(max_positions=2,max_fee_bps=None,max_fee_usd='2')
    report['trial'].update(phase='closing_positions',managed_portfolio=True)
    (tmp_path/'live-status.json').write_text(json.dumps(report))
    result=public_snapshot(tmp_path,103)
    fly=next(b for b in result['bios'] if b['bio_id']=='adult')
    assert len(fly['holdings'])==2 and fly['holdings'][1]['asset_id']==second
    assert fly['phase']=='closing_positions' and result['limits']['max_positions']==2
    assert result['limits']['max_fee_pct'] is None
    assert 'private' not in json.dumps(result) and 'secret' not in json.dumps(result)
    store.close()


def test_pending_and_stale_reports_never_claim_completion_or_activity(tmp_path):
    store,_=fixture(tmp_path);buy(store,False)
    current=public_snapshot(tmp_path,102)
    assert next(b for b in current['bios'] if b['bio_id']=='adult')['phase']=='submitting'
    assert current['orders'][0]['cash_delta_usd'] is None
    stale=public_snapshot(tmp_path,230)
    assert stale['available'] and not stale['fresh'] and not stale['running']
    assert next(b for b in stale['bios'] if b['bio_id']=='adult')['phase']=='review_required'
    store.close()


def test_missing_corrupt_or_wrong_mode_evidence_does_not_create_ledger(tmp_path):
    assert public_snapshot(tmp_path,100)['executor_state']=='not_started'
    assert not (tmp_path/'live.sqlite').exists()
    (tmp_path/'live-status.json').write_text('{broken')
    assert public_snapshot(tmp_path,100)['executor_state']=='unavailable'
    store,report=fixture(tmp_path)
    report['mode']='shadow';(tmp_path/'live-status.json').write_text(json.dumps(report))
    assert not public_snapshot(tmp_path,102)['available']
    store.close()


def test_public_endpoint_has_no_mutation_route(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from bio_arena.market_board import app
    monkeypatch.setenv('BIO_ARENA_EXECUTION_DIR',str(tmp_path))
    client=TestClient(app)
    response=client.get('/api/execution')
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()['executor_state']=='not_started'
    assert client.post('/api/execution').status_code==405
    assert not (tmp_path/'live.sqlite').exists()


def test_acceptance_check_is_identified_separately_from_bio_policy(tmp_path):
    store,report=fixture(tmp_path)
    report.update(execution_kind='operator_check',check_stage='incomplete',process_running=False)
    (tmp_path/'live-status.json').write_text(json.dumps(report))
    result=public_snapshot(tmp_path,102)
    assert result['execution_kind']=='operator_check' and result['check_stage']=='incomplete'
    assert next(b for b in result['bios'] if b['bio_id']=='adult')['phase']=='check_incomplete'
    assert not result['trial']['complete']
    store.close()


def test_policy_audit_exposes_counts_and_reason_codes_without_raw_signals(tmp_path):
    store,report=fixture(tmp_path)
    report['policy_audit']={'adult':{'actions':{'BUY':8,'private-account':1},
        'outcomes':{'held':8},'reasons':{'Paper exploration is excluded from live execution':8,'secret-wallet':1},
        'decision':{'token':'secret-token'}}}
    (tmp_path/'live-status.json').write_text(json.dumps(report))
    result=public_snapshot(tmp_path,102)
    assert result['policy_audit']['adult']['actions']=={'BUY':8}
    assert result['policy_audit']['adult']['reasons']['paper_exploration']==8
    assert 'secret' not in json.dumps(result) and 'private-account' not in json.dumps(result)
    store.close()
