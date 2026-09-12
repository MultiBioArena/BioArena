from copy import deepcopy
import sqlite3

import pytest

from bio_arena.execution_preflight import IntentJournal, LivePlan, review


def fixture():
    address='0x'+'a'*40
    intent={'id':'one','bio_id':'worm','chain':'robinhood','address':address,'action':'BUY','amount_usd':'10'}
    account={'account_ref':'a','identity_verified':True,'balances_reconciled':True,'gas_sufficient':True,
             'observed_at':100,'cash_usd':'100','positions':[],'pending_orders':[]}
    quote={'account_ref':'a','asset_id':f'robinhood:{address}','observed_at':100,'expires_at':110,
           'executable_quote':True,'route_id':'offline-fixture','side':'BUY','amount_usd':'10','total_cost_usd':'10.3'}
    return intent,account,quote,{'worm':'a','adult':'b','larva':'c'}


def test_successful_fixture_preflight_never_enables_submission():
    args=fixture();result=review(*args,now=101)
    assert result['checks_passed'] and not result['can_submit']
    with pytest.raises(ValueError,match='not connected'):LivePlan(enabled=True)
    with pytest.raises(ValueError):LivePlan(max_positions=5)


@pytest.mark.parametrize('part,field,value',[(1,'cash_usd','0'),(1,'identity_verified',False),
    (1,'account_ref','b'),(1,'observed_at',20),(1,'gas_sufficient',False),
    (1,'positions',[{'asset_id':'other'}]),(1,'pending_orders',[{'status':'unknown'}]),
    (2,'executable_quote',False),(2,'asset_id','base:wrong'),(2,'expires_at',100),
    (2,'total_cost_usd',None),(2,'amount_usd','20'),(0,'amount_usd','50'),
    (2,'expires_at',float('inf')),(1,'identity_verified','false'),(1,'balances_reconciled','true'),
    (1,'pending_orders',[{'status':'prepared'}])])
def test_invalid_or_incomplete_evidence_blocks_preparation(part,field,value):
    args=fixture();args[part][field]=value
    assert not review(*args,now=101)['checks_passed']


def test_journal_restart_unknown_order_and_duplicate_delivery(tmp_path):
    args=fixture();check=review(*args,now=101);path=tmp_path/'intents.sqlite'
    journal=IntentJournal(path);assert journal.prepare(args[0],'a',check,now=101)=='prepared'
    assert journal.prepare(args[0],'a',check,now=101)=='prepared'
    changed=deepcopy(args[0]);changed['amount_usd']='20'
    with pytest.raises(ValueError,match='reused'):journal.prepare(changed,'a',check,now=101)
    journal.observe('one','submitted:1','submitted',{'reference':'fixture:submission'},102)
    journal.observe('one','unknown:1','unknown',{'reference':'fixture:timeout'},103);journal.close()
    journal=IntentJournal(path)
    with pytest.raises(ValueError,match='cannot be resubmitted'):
        journal.observe('one','retry:1','submitted',{'reference':'fixture:retry'},104)
    other=deepcopy(args[0]);other['id']='two'
    other_check=review(other,*args[1:],now=101)
    with pytest.raises(sqlite3.IntegrityError):journal.prepare(other,'a',other_check,now=101)
    journal.observe('one','receipt:1','filled',{'reference':'fixture:receipt'},105)
    journal.observe('one','receipt:1','filled',{'reference':'fixture:receipt'},106)
    assert journal.prepare(other,'a',other_check,now=101)=='prepared'
    journal.close()


def test_preflight_is_bound_to_exact_amount_and_account_and_sell_holding():
    args=fixture();result=review(*args,now=101);journal=IntentJournal(':memory:')
    altered=deepcopy(args[0]);altered['amount_usd']='20'
    with pytest.raises(ValueError,match='content'):journal.prepare(altered,'a',result,now=101)
    with pytest.raises(ValueError,match='expired'):journal.prepare(args[0],'a',result,now=200)
    journal.close()
    intent,account,quote,bindings=args
    intent.update(action='SELL',quantity='1')
    quote.update(side='SELL',quantity='1',minimum_proceeds_usd='9.7',all_fees_included=True)
    assert not review(*args,now=101)['checks_passed']
    account['positions']=[{'asset_id':quote['asset_id'],'quantity':'1'}]
    assert review(*args,now=101)['checks_passed']
    quote['asset_id']=quote['asset_id'].replace('robinhood','base')
    assert not review(*args,now=101)['checks_passed']
