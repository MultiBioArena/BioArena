from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import math

import numpy as np
import pytest
import yaml

from bio_arena.learning import ReadoutLearner, FEATURE_NAMES
from bio_arena.meme_market import address_key, read_board, pair_quote, MemeMarket
from bio_arena.portfolio import PortfolioBroker, position_limit

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def settings():
    result = yaml.safe_load((ROOT / 'configs/fomo.yaml').read_text())['memecoin']
    result['trade_cooldown_seconds'] = 0
    return result


def quote(n=1, now=100, chain='bnb', price=10):
    address = '0x' + f'{n:040x}'
    return {'asset_id': f'{chain}:{address}', 'chain': chain, 'address': address,
            'symbol': 'SAME', 'price': price, 'received_at': now, 'id': f'q:{n}:{now}',
            'liquidity_usd': 1e8, 'volume_5m_usd': 1e6, 'sells_5m': 100,
            'pair_address': f'pair-{n}', 'pair_created_at': 1, 'buys_5m': 100,
            'change_5m_pct': 1., 'minute_volume': 200000}


def intent(q, id='one', action='BUY', bio='worm', allocation=.05):
    return {'id': id, 'asset_id': q['asset_id'], 'bio_id': bio, 'action': action,
            'created_at': q['received_at'] - 1, 'reason': 'fixture',
            'allocation_fraction': allocation, 'sell_fraction': 1.}


def test_five_slots_independent_accounts_and_release_after_sale(settings):
    b = PortfolioBroker(10000, settings, .2)
    for n in range(1, 6):
        q = quote(n)
        assert b.execute(intent(q, str(n)), q, 100)['status'] == 'filled'
    assert len(b.accounts['worm'].positions) == 5
    q = quote(6)
    assert 'Maximum' in b.execute(intent(q, 'six'), q, 100)['reason']
    assert b.execute(intent(q, 'fly-one', bio='adult'), q, 100)['status'] == 'filled'
    q = quote(1)
    assert b.execute(intent(q, 'exit', 'SELL'), q, 100)['status'] == 'filled'
    q = quote(6)
    assert b.execute(intent(q, 'six-retry-new'), q, 100)['status'] == 'filled'
    assert len(b.accounts['worm'].positions) == 5
    assert len(b.accounts['adult'].positions) == 1
    assert not b.accounts['larva'].positions


def test_chain_identity_wrong_quote_and_sell_contract(settings):
    b = PortfolioBroker(10000, settings, .2)
    q, other = quote(), quote(chain='base')
    assert b.execute(intent(q), other, 100)['status'] == 'rejected'
    assert b.execute(intent(q, 'buy'), q, 100)['status'] == 'filled'
    result = b.execute(intent(other, 'wrong-chain', 'SELL'), other, 100)
    assert result['status'] != 'filled'
    assert q['asset_id'] in b.accounts['worm'].positions


def test_duplicate_intents_do_not_change_cash_or_positions(settings):
    b = PortfolioBroker(10000, settings, .2)
    q = quote()
    b.execute(intent(q), q, 100)
    before = b.accounts['worm'].public(100)
    assert b.execute(intent(q), q, 100)['status'] == 'duplicate'
    assert before == b.accounts['worm'].public(100)


def test_future_quotes_and_stale_marks_block_new_exposure(settings):
    b = PortfolioBroker(10000, settings, .2)
    q = quote()
    i = intent(q)
    i['created_at'] = 100
    assert b.execute(i, q, 100)['status'] == 'unfilled'
    assert b.execute(intent(q, 'buy'), q, 100)['status'] == 'filled'
    new = quote(2, now=200)
    assert 'stale mark' in b.execute(intent(new, 'stale-portfolio'), new, 200)['reason']
    assert b.accounts['worm'].public(200)['valuation_stale']
    stale = quote(3, now=100)
    assert b.execute(intent(stale, 'stale'), stale, 200)['status'] == 'unfilled'


def test_partial_sale_cost_basis_and_net_profit_reconcile(settings):
    b = PortfolioBroker(10000, settings, .2)
    q = quote()
    buy = b.execute(intent(q), q, 100)
    account = b.accounts['worm']
    initial_basis = account.positions[q['asset_id']].cost_basis
    sell_q = quote(now=101, price=11)
    i = intent(sell_q, 'half', 'SELL')
    i['sell_fraction'] = .5
    sell = b.execute(i, sell_q, 101)
    assert sell['status'] == 'filled'
    p = account.positions[q['asset_id']]
    assert p.cost_basis == pytest.approx(initial_basis / 2)
    assert account.cash == pytest.approx(10000 - buy['notional'] - buy['fee'] + sell['notional'] - sell['fee'])
    assert account.realized_pnl == pytest.approx(sell['notional'] - sell['fee'] - initial_basis / 2)
    public = account.public(101)
    assert public['pnl'] == pytest.approx(account.realized_pnl + public['positions'][0]['unrealized_pnl'])


def test_retired_holdings_remain_valued_and_can_exit(settings):
    b = PortfolioBroker(10000, settings, .2)
    q = quote()
    b.execute(intent(q), q, 100)
    b.mark({})
    assert b.accounts['worm'].equity() > b.accounts['worm'].cash
    sell = quote(now=101)
    assert b.execute(intent(sell, 'exit', 'SELL'), sell, 101, entry_allowed=False)['status'] == 'filled'


def test_risk_exit_bypasses_cooldown_and_does_not_erase_position(settings):
    settings['trade_cooldown_seconds'] = 1000
    b = PortfolioBroker(10000, settings, .99)
    q = quote()
    b.execute(intent(q), q, 100)
    q = quote(now=101, price=1)
    b.mark({q['asset_id']: q})
    assert b.accounts['worm'].liquidating
    missing_depth = {**q, 'liquidity_usd': 0}
    assert b.execute(intent(q, 'no-depth', 'SELL'), missing_depth, 101)['status'] == 'unfilled'
    assert b.accounts['worm'].positions and b.accounts['worm'].alive
    assert b.execute(intent(q, 'exit', 'SELL'), q, 101)['status'] == 'filled'
    assert not b.accounts['worm'].positions and not b.accounts['worm'].alive


def test_live_limit_supports_two_and_paper_broker_cannot_execute_live(settings):
    assert position_limit(settings, 'paper') == 5
    assert position_limit(settings, 'live') == 1
    with pytest.raises(ValueError, match='not implemented'):
        PortfolioBroker(10000, settings, .2, mode='live')
    settings['live_max_positions'] = 2
    assert position_limit(settings, 'live') == 2
    settings['live_max_positions'] = 3
    with pytest.raises(ValueError):
        position_limit(settings, 'live')


def test_cash_and_exposure_never_exceed_budget(settings):
    b = PortfolioBroker(10000, settings, .2)
    for n in range(1, 20):
        q = quote((n % 5) + 1)
        b.execute(intent(q, str(n), allocation=.2), q, 100)
        a = b.accounts['worm']
        assert a.cash >= 0
        assert len(a.positions) <= 5
        assert (a.equity() - a.cash) / a.equity() <= .601


def test_address_case_and_stale_board(settings):
    assert address_key('bnb', '0x' + 'AB' * 20) == '0x' + 'ab' * 20
    sol = '6dBrKbJdAzkwJvkWEWTJb3iWY7aNbrZKLsrKUCnXxWsM'
    assert address_key('solana', sol) == sol
    q = quote()
    payload = {'schema': 'bio_arena.fomo_market_snapshot.v2', 'board': 'trending',
               'observed_at': datetime.fromtimestamp(100, timezone.utc).isoformat(),
               'candidates': [{**q, 'url': 'https://fomo.family/tokens/bnb/' + q['address'], 'visible_global_position': 1}]}
    assert len(read_board(payload, 101, 180)[1]) == 1
    with pytest.raises(ValueError, match='stale'):
        read_board(payload, 500, 180)


def test_dex_binding_rejects_wrong_chain_and_quote_side(settings):
    q = quote()
    row = {'chainId': 'bsc', 'baseToken': {'address': q['address']}, 'quoteToken': {'address': quote(2)['address']},
           'priceUsd': '2', 'liquidity': {'usd': 50000}, 'pairAddress': 'pool',
           'volume': {'m5': 1000}, 'txns': {'m5': {'buys': 2, 'sells': 2}}, 'pairCreatedAt': 1000}
    found = pair_quote(q, [row], 200)
    assert found['price'] == 2 and not found['executable_quote']
    assert pair_quote(quote(chain='base'), [row], 200) is None
    assert pair_quote(quote(2), [row], 200) is None
    assert pair_quote(q, [{**row, 'priceUsd': 'NaN'}], 200) is None


def learner_settings(settings):
    result = deepcopy(settings['learning'])
    result.update(label_horizon_seconds=10, label_grace_seconds=30,
                  minimum_training_samples=2, validation_samples=2, learning_rate=.5)
    return result


def test_learning_waits_for_future_labels_and_preserves_bio_isolation(settings):
    s = learner_settings(settings)
    a, b = ReadoutLearner('worm', 1, s), ReadoutLearner('adult', 1, s)
    vector = [1.] + [0.] * (len(FEATURE_NAMES) - 1)
    a.watch('sample', quote(now=100), vector, 20, 100)
    assert a.observe({quote()['asset_id']: quote(now=109, price=11)}, 109, 30) == []
    assert a.updates == 0
    outcomes = a.observe({quote()['asset_id']: quote(now=111, price=11)}, 111, 30)
    assert len(outcomes) == 1 and a.updates == 1
    assert outcomes[0]['reward_bps'] == pytest.approx(math.log(1.1) * 10000 - 20)
    assert np.any(a.working != 0) and np.all(a.active == 0) and np.all(b.working == 0)
    assert a.observe({quote()['asset_id']: quote(now=112)}, 112, 30) == []


def test_candidate_is_validated_only_on_observations_after_freeze(settings):
    s = learner_settings(settings)
    learner = ReadoutLearner('worm', 1, s)
    vector = [1.] + [0.] * (len(FEATURE_NAMES) - 1)
    for i in range(5):
        now = 100 + i * 20
        q = quote(now=now)
        learner.watch(str(i), q, vector, 0, now)
        learner.observe({q['asset_id']: quote(now=now+11, price=10.1)}, now+11, 30)
        if i == 1:
            assert learner.candidate and learner.candidate['count'] == 0
            assert learner.active_version == 0
    assert learner.active_version > 0
    assert learner.events[0]['accepted']
    assert learner.events[0]['count'] == 2
    assert learner.events[0]['frozen_at'] < learner.events[0]['evaluated_at']
    state = learner.checkpoint()
    assert state['active_weights'] != [0.] * len(FEATURE_NAMES)
    assert state['feature_names'] == FEATURE_NAMES


def test_missing_or_changed_pool_labels_never_become_zero_returns(settings):
    learner = ReadoutLearner('worm', 1, learner_settings(settings))
    vector = [1.] * len(FEATURE_NAMES)
    learner.watch('missing', quote(), vector, 20, 100)
    learner.observe({}, 141, 30)
    learner.watch('changed', quote(now=150), vector, 20, 150)
    learner.observe({quote()['asset_id']: {**quote(now=161), 'pair_address': 'other'}}, 161, 30)
    assert learner.updates == 0 and learner.expired == 2
    assert not learner.pending
