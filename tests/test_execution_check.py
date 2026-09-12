import pytest

from bio_arena.auto_execution import ExecutionLimits, ExecutionStore
from bio_arena.execution_check import ExecutionCheck


TOKEN='0x'+'1'*40


def setup(tmp_path, mode='live', failure=None):
    now=[100.0]
    calls=[]
    store=ExecutionStore(tmp_path/'check.sqlite',mode,{'adult':'fixture-account'},
        ExecutionLimits(buy_usd='5',max_fee_usd='2',max_fee_bps=1000))

    class Adapter:
        def execute(self,intent,limits,*,live):
            calls.append(intent)
            if not live:return {'status':'shadow','clicked':False}
            if failure and intent['action']==failure[0]:
                return {'status':failure[1],'clicked':failure[1]=='unknown','reason':'Fixture failure'}
            now[0]+=1
            buy=intent['action']=='BUY'
            return {'status':'filled','clicked':True,'account_ref':intent['account_ref'],
                'asset_id':intent['asset_id'],'action':intent['action'],'route_id':intent['id'],
                'relay_status':'SUCCESS','balances_verified':True,'observed_at':now[0],
                'cash_delta_usd':-5 if buy else 4.7,
                'position_after':{'asset_id':intent['asset_id'],'raw_quantity':'1234567','decimals':6} if buy else None}

    adapter=Adapter()
    def make(token=TOKEN, enabled=lambda:True):
        return ExecutionCheck(store,adapter,'adult',token,'fixture-check',clock=lambda:now[0],
            sleep=lambda seconds:now.__setitem__(0,now[0]+seconds),enabled=enabled)
    return store,now,calls,make


def test_acceptance_check_executes_pair_without_a_policy_feed_and_cannot_repeat(tmp_path):
    store,now,calls,make=setup(tmp_path)
    result=make().run()
    assert result['trial']['complete'] and result['check_stage']=='complete'
    assert result['trial']['cash_change_usd']==pytest.approx(-0.3)
    assert [i['action'] for i in calls]==['BUY','SELL']
    assert all(i['source_kind']=='operator_execution_check' for i in calls)
    assert calls[1]['quantity_raw']=='1234567' and calls[1]['created_at']>=221
    assert store.holding('adult') is None and not result['process_running']
    assert make().run()['trial']['complete'] and len(calls)==2
    with pytest.raises(ValueError,match='immutable'):make('0x'+'2'*40)
    store.close()


@pytest.mark.parametrize('failure',[('BUY','blocked'),('BUY','unknown'),('SELL','unknown')])
def test_failed_or_uncertain_step_is_incomplete_and_never_retried(tmp_path,failure):
    store,now,calls,make=setup(tmp_path,failure=failure)
    first=make().run()
    assert not first['trial']['complete'] and first['check_stage']=='incomplete'
    count=len(calls)
    assert not make().run()['trial']['complete'] and len(calls)==count
    if failure[0]=='SELL':
        assert store.holding('adult') is not None and first['trial']['real_orders_verified']==1
    store.close()


def test_default_quote_rehearsal_does_not_try_to_sell(tmp_path):
    store,now,calls,make=setup(tmp_path,mode='shadow')
    result=make().run()
    assert result['check_stage']=='quote_only' and not result['trial']['complete']
    assert [i['action'] for i in calls]==['BUY'] and store.holding('adult') is None
    store.close()


def test_operator_stop_after_entry_keeps_position_and_resume_only_sells(tmp_path):
    store,now,calls,make=setup(tmp_path)
    first=make(enabled=lambda:len(calls)==0).run()
    assert first['check_stage']=='stopped' and store.holding('adult') is not None
    result=make().run()
    assert result['trial']['complete'] and [i['action'] for i in calls]==['BUY','SELL']
    store.close()


def test_expired_verified_entry_can_get_an_explicit_exit_window_without_rebuy(tmp_path):
    store,now,calls,make=setup(tmp_path)
    make(enabled=lambda:len(calls)==0).run()
    now[0]=1000
    check=make()
    assert check.trial.state(now[0])['phase']=='expired'
    check.resume_exit_window()
    assert check.run()['trial']['complete']
    assert [i['action'] for i in calls]==['BUY','SELL']
    assert store.db.execute('SELECT previous_deadline,deadline FROM execution_exit_windows').fetchone()==(700,1600)
    make().resume_exit_window()
    assert len(calls)==2
    store.close()


@pytest.mark.parametrize('failure',[None,('BUY','unknown'),('SELL','unknown')])
def test_exit_resume_cannot_start_a_buy_or_retry_an_uncertain_attempt(tmp_path,failure):
    store,now,calls,make=setup(tmp_path,failure=failure)
    if failure:make().run()
    with pytest.raises(ValueError,match='one verified entry'):make().resume_exit_window()
    store.close()


def retry_fixture(tmp_path,action,failures,*,retryable=True,status='blocked'):
    store=ExecutionStore(tmp_path/'retry.sqlite','live',{'adult':'fixture'},ExecutionLimits())
    now=[100.0];calls=[];remaining=[failures]
    class Adapter:
        def execute(self,intent,limits,*,live):
            calls.append(intent)
            if intent['action']==action and remaining[0]:
                remaining[0]-=1
                return {'status':status,'clicked':status=='unknown','retryable':retryable,
                        'reason':'Browser operation failed','failure_stage':'select_amount'}
            buy=intent['action']=='BUY';now[0]+=1
            return {'status':'filled','clicked':True,'account_ref':intent['account_ref'],
                'asset_id':intent['asset_id'],'action':intent['action'],'route_id':intent['id'],
                'relay_status':'SUCCESS','balances_verified':True,'observed_at':now[0],
                'cash_delta_usd':-2 if buy else 1.8,
                'position_after':{'asset_id':intent['asset_id'],'raw_quantity':'2000000','decimals':6} if buy else None}
    adapter=Adapter()
    def make():
        return ExecutionCheck(store,adapter,'adult',TOKEN,'retry-check',clock=lambda:now[0],
            sleep=lambda seconds:now.__setitem__(0,now[0]+seconds))
    return store,now,calls,make


@pytest.mark.parametrize('action',['BUY','SELL'])
def test_transient_unsubmitted_ui_failures_retry_in_one_run_with_distinct_ids(tmp_path,action):
    store,now,calls,make=retry_fixture(tmp_path,action,2)
    assert make().run()['trial']['complete']
    attempts=[i for i in calls if i['action']==action]
    assert len(attempts)==3 and len({i['id'] for i in attempts})==3
    assert store.report()['counts']=={'blocked':2,'filled':2}
    assert all(i['asset_id']=='robinhood:'+TOKEN for i in calls)
    store.close()


def test_retry_budget_survives_restart_and_unknown_is_never_retried(tmp_path):
    store,now,calls,make=retry_fixture(tmp_path,'BUY',10)
    assert not make().run()['trial']['complete'] and len(calls)==3
    assert not make().run()['trial']['complete'] and len(calls)==3
    store.close()
    other=tmp_path/'unknown';other.mkdir()
    store,now,calls,make=retry_fixture(other,'BUY',10,status='unknown')
    assert not make().run()['trial']['complete'] and len(calls)==1
    assert not make().run()['trial']['complete'] and len(calls)==1
    store.close()


def test_explicit_exit_resume_preserves_old_blocked_attempt_and_never_buys_again(tmp_path):
    store,now,calls,make=retry_fixture(tmp_path,'SELL',1,retryable=False)
    assert not make().run()['trial']['complete'] and len(calls)==2
    now[0]=1000;check=make();check.resume_exit_window()
    assert check.run()['trial']['complete']
    assert [i['action'] for i in calls]==['BUY','SELL','SELL']
    assert calls[-1]['id']=='retry-check:SELL:retry-2'
    assert store.status('retry-check:SELL')=='blocked'
    store.close()
