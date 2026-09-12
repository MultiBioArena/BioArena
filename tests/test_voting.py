"""EVM eligibility and HTTP voting use offline fixtures only, never wallet signatures."""
import asyncio
import json
import time

import httpx
import pytest

from bio_arena.audience import RequestBudget, create_app
from bio_arena.challenge import ChallengeStore
from bio_arena.voting import EvmEligibility, HoldingUnavailable, VoteSettings, evm_address
from test_challenge import T, snap

ADDRESS = '0x' + 'aB' * 20
TOKEN = '0x' + '11' * 20
SETTINGS = VoteSettings(mode='token_holder',chain_id=999,rpc_url='https://rpc.invalid/private-key',token=TOKEN,minimum_raw=10**20)


def rpc_fixture(amount=10**20, chain=999, malformed=False, reorg=False, stale=False, empty_code=False):
    calls = []
    def handle(request):
        p = json.loads(request.content);method = p['method'];calls.append(p)
        result = {'eth_chainId':hex(chain),'eth_blockNumber':hex(100),
                  'eth_getCode':'0x' if empty_code else '0x6080',
                  'eth_call':'0x1' if malformed else '0x'+f'{amount:064x}',
                  'eth_getBlockByNumber':{'number':hex(97),'hash':'0x'+('b' if reorg and len(calls)>5 else 'a')*64,
                                          'timestamp':hex(int(time.time())-(1000 if stale else 0))}}[method]
        return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':result})
    return httpx.MockTransport(handle),calls


def test_address_normalization_and_bad_addresses():
    assert evm_address(ADDRESS) == ADDRESS.lower()
    for address in ['','0x'+'0'*40,'0x'+'z'*40,'0x'+'1'*39,'SolanaAddress',None]:
        with pytest.raises(ValueError): evm_address(address)


def test_holder_balance_uses_exact_integers_and_fixed_chain_block_contract():
    async def exercise():
        transport,calls = rpc_fixture()
        async with httpx.AsyncClient(transport=transport) as client:
            record = await EvmEligibility(SETTINGS,client).check(ADDRESS)
        assert record['eligible'] and record['balance_raw'] == str(10**20)
        assert record['block_number'] == 97 and record['chain_id'] == 999
        assert not record['ownership_verified']
        call = next(p for p in calls if p['method']=='eth_call')
        assert call['params'] == [{'to':TOKEN,'data':'0x70a08231'+ADDRESS[2:].lower().rjust(64,'0')},'0x61']
        assert all(p['method'] in ('eth_chainId','eth_blockNumber','eth_getBlockByNumber','eth_getCode','eth_call') for p in calls)
    asyncio.run(exercise())


@pytest.mark.parametrize('kwargs', [{'chain':1},{'malformed':True},{'reorg':True},{'stale':True},{'empty_code':True}])
def test_holder_check_rejects_wrong_chain_bad_contract_reorg_and_old_data(kwargs):
    async def exercise():
        transport,_ = rpc_fixture(**kwargs)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(HoldingUnavailable): await EvmEligibility(SETTINGS,client).check(ADDRESS)
    asyncio.run(exercise())


def test_rpc_errors_do_not_expose_provider_credentials_or_count_votes():
    async def exercise():
        def fail(request): return httpx.Response(429,text='https://rpc.invalid/private-key')
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            with pytest.raises(HoldingUnavailable) as caught: await EvmEligibility(SETTINGS,client).check(ADDRESS)
        assert 'private-key' not in str(caught.value)
        transport,_ = rpc_fixture(amount=10**20-1)
        async with httpx.AsyncClient(transport=transport) as client:
            assert not (await EvmEligibility(SETTINGS,client).check(ADDRESS))['eligible']
    asyncio.run(exercise())


def test_paper_votes_duplicate_case_cutoff_receipt_and_restart(tmp_path,monkeypatch):
    clock = [T+100]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    path = tmp_path/'votes.sqlite3'
    config = VoteSettings(mode='paper_test')
    async def exercise():
        app = create_app(path,config,collect=False)
        async with app.router.lifespan_context(app):
            store = app.state.store
            store.observe(snap(T+1),config.public())
            app.state.last_received,app.state.error = clock[0],None
            round_id = store.view(clock[0])['current']['id']
            payload = {'round_id':round_id,'address':ADDRESS,'bio_id':'worm'}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                responses = await asyncio.gather(*[client.post('/api/challenge/votes',json=payload|{'address':a}) for a in [ADDRESS,ADDRESS.lower(),ADDRESS.upper().replace('0X','0x')]])
                assert all(r.status_code==200 for r in responses)
                receipt = responses[0].json()['receipt']
                assert all(r.json()['receipt']==receipt for r in responses)
                duplicate = await client.post('/api/challenge/votes',json=payload|{'bio_id':'adult'})
                assert duplicate.status_code == 409
                view = (await client.get('/api/challenge')).json()
                assert view['current']['counts']['worm'] == 1
                assert ADDRESS.lower() not in json.dumps(view)
                assert (await client.get('/api/challenge/receipts/'+receipt)).json()['prediction_status'] == 'pending'
                clock[0] = T+900
                locked = await client.post('/api/challenge/votes',json=payload|{'address':'0x'+'22'*20})
                assert locked.status_code == 409
                clock[0] = T+3601
                store.observe(snap(clock[0],(90,990,9990)),config.public())
                result = (await client.get('/api/challenge/receipts/'+receipt)).json()
                assert result['prediction_status']=='correct' and result['rewards']=='not_enabled'
                assert result['ownership_verified'] is False
                assert 'address' not in result
        reopened = ChallengeStore(path)
        assert reopened.receipt(receipt)['prediction_status'] == 'correct'
        reopened.close()
    asyncio.run(exercise())


def test_disabled_gate_stale_source_payload_limit_and_gate_change(tmp_path,monkeypatch):
    monkeypatch.setattr(time,'time',lambda:T+100)
    async def exercise():
        app = create_app(tmp_path/'a.sqlite3',VoteSettings(),collect=False)
        async with app.router.lifespan_context(app):
            app.state.store.observe(snap(T+1),VoteSettings().public())
            rid = app.state.store.view(T+100)['current']['id']
            payload = {'round_id':rid,'address':ADDRESS,'bio_id':'adult'}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                assert (await client.post('/api/challenge/votes',json=payload)).status_code==403
                assert (await client.post('/api/challenge/votes',content='x'*2048,headers={'Content-Type':'application/json'})).status_code==413
                assert (await client.post('/api/challenge/votes',json=payload|{'balance':100})).status_code==400
                app.state.settings = VoteSettings(mode='paper_test')
                assert (await client.post('/api/challenge/votes',json=payload)).status_code==409
                app.state.store.observe(snap(T+3601),app.state.settings.public())
                monkeypatch.setattr(time,'time',lambda:T+3602)
                payload['round_id'] = app.state.store.view(T+3602)['current']['id']
                assert (await client.post('/api/challenge/votes',json=payload)).status_code==503
    asyncio.run(exercise())


def test_rpc_finishing_after_cutoff_does_not_record_vote(tmp_path,monkeypatch):
    clock = [T+899];monkeypatch.setattr(time,'time',lambda:clock[0])
    async def exercise():
        config=VoteSettings(mode='paper_test');app=create_app(tmp_path/'a.sqlite3',config,collect=False)
        async with app.router.lifespan_context(app):
            app.state.store.observe(snap(T+1),config.public());app.state.last_received=clock[0];app.state.error=None
            async def slow(address):
                clock[0]=T+900
                return {'eligible':True,'address':address,'token':None,'chain_id':None,'checked_at':clock[0]}
            app.state.eligibility.check=slow
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                result=await client.post('/api/challenge/votes',json={'round_id':app.state.store.view(T+100)['current']['id'],'address':ADDRESS,'bio_id':'worm'})
                assert result.status_code==409
                assert app.state.store.db.execute('SELECT COUNT(*) FROM votes').fetchone()[0]==0
    asyncio.run(exercise())


def test_request_budget_is_bounded_and_resets():
    from fastapi import HTTPException
    budget=RequestBudget()
    for _ in range(8): budget.take('ip',T)
    with pytest.raises(HTTPException): budget.take('ip',T)
    budget.take('ip',T+60)
    assert len(budget.clients)==1 and budget.total==1
