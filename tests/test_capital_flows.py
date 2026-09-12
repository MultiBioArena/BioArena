import asyncio
from copy import deepcopy
from decimal import Decimal

import pytest

from bio_arena.capital_flows import FlowStore, scan
from bio_arena.challenge import ChallengeStore, performance
from bio_arena.evm_readonly import TRANSFER
from test_challenge import T, GATE, snap
from test_evm_readonly import WALLET,TOKEN,OTHER,TX,BLOCK


def receipt(amount=100_000_000):
    return {'status':'confirmed_success','chain_id':4663,'wallet':WALLET,'tx_hash':TX,'block_number':100,
        'block_hash':BLOCK,'scope':'verified fixture','fee_payer':OTHER,
        'transfers':[{'event_id':f'4663:{TX}:0','token':TOKEN,'delta_raw':str(amount),'from':OTHER if amount>0 else WALLET,
                      'to':WALLET if amount>0 else OTHER,'log_index':0}]}


def valuation(before='90',after='189.5',amount=100_000_000,fee='.5'):
    return {'chain_id':4663,'wallet':WALLET,'tx_hash':TX,'reference':'fixture:balances','price_snapshot_id':'fixture:prices',
        'balances_verified':True,'at':T+100,'equity_before':before,'equity_after':after,'transaction_cost_usd':fee,
        'balance_changes_raw':{TOKEN:str(amount)},'tokens':{TOKEN:{'price_usd':'1','decimals':6,'source':'fixture:mark',
        'observed_at':T+100,'price_snapshot_id':'fixture:prices'}}}


def test_deposit_reconciliation_does_not_erase_losses_or_fees_and_survives_restart(tmp_path):
    path=tmp_path/'flows.sqlite';store=FlowStore(path)
    store.record('worm',receipt(),T+100,'deposit');store.record('worm',receipt(),T+100,'deposit')
    f=store.reconcile('worm',TX,valuation());store.close();store=FlowStore(path)
    assert store.reconcile('worm',TX,valuation())==f
    rows=store.for_interval('worm',T,T+3600,require_coverage=False)
    assert performance(100,189.5,T,T+3600,rows)['return_pct']==pytest.approx(-10.5)
    changed=valuation();changed['reference']='different'
    with pytest.raises(ValueError,match='immutable'):store.reconcile('worm',TX,changed)
    store.close()


def test_withdrawal_cost_and_unclassified_transfer_block_scoring():
    store=FlowStore(':memory:');store.record('worm',receipt(-20_000_000),T+100,'withdrawal')
    store.reconcile('worm',TX,valuation('100','79.5',-20_000_000))
    result=performance(100,79.5,T,T+3600,store.for_interval('worm',T,T+3600,False))
    assert result['return_pct']==pytest.approx(-.5)
    with pytest.raises(ValueError,match='coverage'):store.for_interval('worm',T,T+3600)
    store.close();store=FlowStore(':memory:');store.record('worm',receipt(),T+100,'review')
    with pytest.raises(ValueError,match='Unclassified'):store.reconcile('worm',TX,valuation())
    with pytest.raises(ValueError,match='Unreconciled'):store.for_interval('worm',T,T+3600,False)
    store.close()


def test_one_transfer_can_be_observed_by_two_independent_bio_wallets():
    store=FlowStore(':memory:')
    incoming=receipt()
    outgoing=deepcopy(incoming);outgoing['wallet']=OTHER
    outgoing['transfers'][0]['delta_raw']='-100000000'
    store.record('worm',incoming,T+100,'deposit')
    store.record('adult',outgoing,T+100,'withdrawal')
    store.record('worm',incoming,T+100,'deposit')
    store.record('adult',outgoing,T+100,'withdrawal')
    assert store.db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0]==2
    assert {r[0] for r in store.db.execute('SELECT bio FROM transfers')}=={'worm','adult'}
    store.record('worm',outgoing,T+100,'withdrawal')
    store.record('worm',outgoing,T+100,'withdrawal')
    assert store.db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0]==3
    store.close()


def test_hourly_store_uses_persistent_flows_and_missing_coverage_voids():
    store=FlowStore(':memory:');store.record('worm',receipt(),T+100,'deposit')
    store.reconcile('worm',TX,valuation('90','190',fee='0'))
    with store.db:
        for bio in ['worm','adult','larva']:store.db.execute('INSERT INTO coverage VALUES (?,?,?,?,0)',(bio,bio,T-1,T+3601))
    challenge=ChallengeStore(':memory:',store)
    challenge.observe(snap(T,(100,100,100)),GATE)
    challenge.observe(snap(T+3600,(190,95,96)),GATE)
    result=challenge.view(T+3600)['history'][0]['result']
    assert result['winners']==['worm'] and result['rows'][0]['net_flow_usd']==100
    challenge.close()
    broken=ChallengeStore(':memory:',FlowStore(':memory:'))
    broken.observe(snap(T),GATE);broken.observe(snap(T+3600),GATE)
    assert broken.view(T+3600)['history'][0]['status']=='void'
    broken.close();store.close()


class Reader:
    chain_id=4663;confirmations=3
    def __init__(self,direct=True,reorg=False):self.direct=direct;self.reorg=reorg
    async def height(self):return 110
    async def block(self,n):return {'hash':'0x'+'c'*64 if self.reorg else BLOCK,'timestamp':hex(T+n),'number':hex(n)}
    async def receipt(self,*args):return receipt()
    async def rpc(self,method,args):
        if method=='eth_getLogs':
            return [{'transactionHash':TX,'logIndex':'0x0','blockNumber':'0x64'}] if args[0]['topics'][1] is None else []
        if method=='eth_getTransactionByHash':
            return {'hash':TX,'from':OTHER,'to':TOKEN,'input':'0xa9059cbb'+WALLET[2:].rjust(64,'0')+f'{100_000_000:064x}' if self.direct else '0x1234'}
        raise AssertionError(method)


def test_scanner_only_classifies_exact_transfers_from_expected_wallets_and_reorg_blocks():
    async def run():
        binding={'bio_id':'worm','wallet':WALLET,'tokens':[TOKEN],'external_wallets':[OTHER],'start_block':100}
        store=FlowStore(':memory:')
        result=await scan(Reader(),store,binding)
        assert result['classifications']==['deposit']
        assert (await scan(Reader(),store,binding))['scanned']==0
        with pytest.raises(ValueError,match='reorganization'):await scan(Reader(reorg=True),store,binding)
        assert store.db.execute('SELECT blocked FROM coverage').fetchone()[0]==1
        store.close();store=FlowStore(':memory:')
        assert (await scan(Reader(direct=False),store,binding))['classifications']==['review']
        store.close()
    asyncio.run(run())
