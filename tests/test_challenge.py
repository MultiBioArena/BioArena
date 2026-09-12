"""Audience scoring does not mutate the market, accounts or learner."""
import copy

import pytest

from bio_arena.challenge import CapitalFlow, ChallengeStore, performance, paper_snapshot, score
from bio_arena.voting import VoteSettings

T = 3600 * 500000
GATE = VoteSettings(mode='paper_test').public()


def snap(at, values=(100, 1000, 10000), run='paper-fixture', alive=(True, True, True)):
    return {'at': at, 'run_id': run, 'sequence': int(at), 'source_at': at,
            'accounts': {bio: {'equity': n, 'alive': yes} for bio, n, yes in zip(('worm','adult','larva'), values, alive)},
            'capital_flows': []}


def test_percentage_ranks_unequal_capital_not_dollar_loss():
    result = score(snap(T), snap(T + 3600, (90, 950, 9600)))
    assert result['winners'] == ['worm']
    assert [r['return_pct'] for r in result['rows']] == pytest.approx([-10, -5, -4])


def test_reconciled_deposit_and_withdrawal_link_subperiods():
    flows = [CapitalFlow('deposit', T+100, 100, 90, 190, 'ledger:1'),
             CapitalFlow('withdrawal', T+200, -40, 209, 169, 'ledger:2')]
    result = performance(100, 152.1, T, T+3600, flows)
    assert result['return_pct'] == pytest.approx((.9*1.1*.9-1)*100)
    assert result['net_flow_usd'] == 60
    assert result['pnl_usd'] == pytest.approx(-7.9)
    assert performance(100, 200, T, T+3600, [CapitalFlow('d',T+1,100,100,200,'ledger')])['return_pct'] == 0


@pytest.mark.parametrize('flow', [
    CapitalFlow('a',T+1,100,100,201,'ledger'),
    CapitalFlow('a',T+1,100,100,200,''),
    CapitalFlow('a',T,100,100,200,'ledger'),
    CapitalFlow('a',T+3601,100,100,200,'ledger'),
    CapitalFlow('a',T+1,float('nan'),100,200,'ledger'),
])
def test_incomplete_cash_flow_evidence_cannot_be_scored(flow):
    with pytest.raises(ValueError):
        performance(100, 200, T, T+3600, [flow])


def test_duplicate_flows_and_full_withdrawal_fail_closed():
    flow = CapitalFlow('same',T+1,100,100,200,'ledger')
    with pytest.raises(ValueError):
        performance(100,200,T,T+3600,[flow,flow])
    with pytest.raises(ValueError, match='fully withdrawn'):
        performance(100,0,T,T+3600,[CapitalFlow('w',T+1,-100,100,0,'ledger')])


def test_bankruptcy_stays_minus_100_despite_later_refill():
    flow = CapitalFlow('refill',T+500,100,0,100,'ledger')
    result = performance(100,150,T,T+3600,[flow])
    assert result['return_pct'] == -100
    assert result['bankrupt']
    sitting = score(snap(T,(0,100,100)),snap(T+3600,(100,90,95)))
    assert not sitting['rows'][0]['eligible']
    assert sitting['winners'] == ['adult']
    # A newly funded, reactivated account can participate only from the next opening.
    assert score(snap(T+3600,(100,90,95)),snap(T+7200,(90,90,95)))['winners'] == ['worm']


@pytest.mark.parametrize('values,outcome,winners', [
    ((90,900,9000),'tie',['worm','adult','larva']),
    ((101,1001,10001),'no_loss',[]),
    ((100,1000,10000),'no_loss',[]),
    ((0,1000,10000),'winner',['worm']),
])
def test_ties_no_loss_and_zero_equity(values,outcome,winners):
    result = score(snap(T),snap(T+3600,values))
    assert result['outcome'] == outcome and result['winners'] == winners
    assert score(snap(T,alive=(True,False,False)),snap(T+3600,values))['outcome'] == 'insufficient_participants'


def test_three_complete_hours_resume_and_immutable_results(tmp_path):
    path = tmp_path/'rounds.sqlite3'
    store = ChallengeStore(path)
    store.observe(snap(T+3), GATE)
    rid = store.view(T+3)['current']['id']
    # Starting halfway through a service restart must preserve the original opening.
    store.close()
    store = ChallengeStore(path)
    store.observe(snap(T+500,(90,950,9900)), GATE)
    assert store.get(rid)['opening']['accounts']['worm']['equity'] == 100
    for hour, values in enumerate([(90,950,9900),(95,900,9900),(90,890,8000)],1):
        store.observe(snap(T+hour*3600+4,values),GATE)
    history = store.view(T+10805)['history']
    assert len(history) == 3
    assert [r['result']['winners'] for r in history] == [['larva'],['adult'],['worm']]
    original = store.get(rid)
    store.observe(snap(T+10806,(2,2,2)),GATE)
    assert store.get(rid) == original
    store.close()


def test_late_start_missing_boundary_and_run_reset(tmp_path):
    store = ChallengeStore(tmp_path/'a.sqlite3')
    store.observe(snap(T+60),GATE)
    assert store.view(T+60)['current']['status'] == 'warmup'
    store.observe(snap(T+3601),GATE)
    first = store.view(T+3601)['current']['id']
    store.observe(snap(T+7200+21),GATE)
    assert store.get(first)['status'] == 'void'
    store.observe(snap(T+10801),GATE)
    second = store.view(T+10801)['current']['id']
    store.observe(snap(T+10900,run='new-run'),GATE)
    assert store.get(second)['status'] == 'void'
    assert 'run changed' in store.get(second)['reason']
    store.close()


def paper_state():
    return {'mode':'paper','status':'running','paused':False,'market_fresh':True,
            'run_id':'r','server_time':T,'sequence':20,
            'bios':[{'id':b,'account':{'equity':100,'alive':True,'positions':[]}} for b in ('worm','adult','larva')]}


def test_source_adapter_is_read_only_and_refuses_live_stale_and_missing_accounts():
    state = paper_state();before = copy.deepcopy(state)
    assert paper_snapshot(state,T)['accounts']['worm']['equity'] == 100
    assert state == before
    for key,value in [('mode','live'),('paused',True),('market_fresh',False),('server_time',T-60)]:
        invalid = copy.deepcopy(state);invalid[key] = value
        with pytest.raises(ValueError): paper_snapshot(invalid,T)
    for change in ['stale','missing','nan']:
        invalid = copy.deepcopy(state)
        if change == 'stale': invalid['bios'][0]['account']['valuation_stale'] = True
        if change == 'missing': invalid['bios'].pop()
        if change == 'nan': invalid['bios'][0]['account']['equity'] = float('nan')
        with pytest.raises(ValueError): paper_snapshot(invalid,T)


def test_finished_cash_only_ledger_can_close_without_inventing_market_prices():
    state=paper_state();state['status']='finished';state['market_fresh']=False
    for bio in state['bios']:
        bio['account'].update(cash=100,alive=False)
    assert paper_snapshot(state,T)['accounts']['worm']['equity']==100
    state['bios'][0]['account']['positions']=[{'mark_stale':True}]
    with pytest.raises(ValueError):paper_snapshot(state,T)


def test_round_freezes_participants_and_new_bio_joins_next_hour(tmp_path):
    store=ChallengeStore(tmp_path/'dynamic.sqlite')
    first=snap(T)
    store.observe(first,GATE)
    original=store.get(f'paper:paper-fixture:{T}')
    following=snap(T+300)
    following['accounts']['future_bio']={'equity':100,'alive':True}
    store.observe(following,GATE)
    current=store.view(T+300)['current']
    assert set(current['counts']) == {'worm','adult','larva'}
    assert [r['bio_id'] for r in current['result']['rows']] == ['worm','adult','larva']
    closing=snap(T+3600,(90,1000,10000))
    closing['accounts']['future_bio']={'equity':80,'alive':True}
    store.observe(closing,GATE)
    assert store.get(original['id'])['result']['winners']==['worm']
    assert store.view(T+3600)['current']['rules']['participants']==['worm','adult','larva','future_bio']
    assert 'future_bio' in store.view(T+3600)['current']['counts']
    store.close()


def test_missing_frozen_bio_voids_round_instead_of_changing_outcomes(tmp_path):
    store=ChallengeStore(tmp_path/'missing.sqlite');store.observe(snap(T),GATE)
    closing=snap(T+3600);del closing['accounts']['worm']
    store.observe(closing,GATE)
    assert store.get(f'paper:paper-fixture:{T}')['status']=='void'
    store.close()


def test_new_bio_votes_wait_for_the_next_frozen_roster(tmp_path):
    store=ChallengeStore(tmp_path/'new-vote.sqlite');store.observe(snap(T),GATE)
    address='0x'+'a'*40
    evidence={'eligible':True,'address':address,'token':None,'chain_id':None,'checked_at':T+100}
    with pytest.raises(ValueError,match='not participating'):
        store.cast(f'paper:paper-fixture:{T}',address,'future_bio',evidence,T+100)
    next_open=snap(T+3600);next_open['accounts']['future_bio']={'equity':100,'alive':True}
    store.observe(next_open,GATE);evidence['checked_at']=T+3601
    saved=store.cast(f'paper:paper-fixture:{T+3600}',address,'future_bio',evidence,T+3601)
    assert saved['bio_id']=='future_bio'
    assert store.view(T+3601)['current']['counts']['future_bio']==1
    store.close()
