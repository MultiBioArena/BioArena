"""Staggered connectome observations and independent multi-asset paper decisions."""
import asyncio
from collections import defaultdict
from dataclasses import asdict
import json
import math
import time

from .arena import Arena
from .learning import ReadoutLearner, model_features
from .market import FeatureEncoder
from .meme_market import MemeMarket
from .portfolio import PortfolioBroker, cost_bps
from .simulation import advance, save_checkpoint


class MemecoinArena(Arena):
    def __init__(self, root, config=None):
        super().__init__(root, config)
        self.settings = self.config['memecoin']
        self.broker = PortfolioBroker(self.config['initial_cash'], self.settings,
                                      self.config['stop_equity_fraction'], self.config['execution']['mode'], keys=self.keys)
        self.learners = {k: ReadoutLearner(k, self.config['seed'], self.settings['learning']) for k in self.keys}
        self.policies = self.learners
        self.encoders = {k: {} for k in self.keys}
        self.encoder_pairs = {k: {} for k in self.keys}
        self.reviewed = {k: defaultdict(float) for k in self.keys}
        self.focus_assets = {k: None for k in self.keys}
        self.selections = {k: [] for k in self.keys}
        self.board_file = (self.run_dir / 'candidates.jsonl').open('a', buffering=1)
        for table in ('observations', 'model_events', 'account_outcomes'):
            self.db.execute(f'CREATE TABLE {table} (id TEXT PRIMARY KEY, bio_id TEXT, ts REAL, payload TEXT)')
        self.market = MemeMarket(self.root, self.settings, self.record_quote, self.record_board, self.retained_assets)
        self.pending_accounts = {}
        self.frozen_accounts = None

    def retained_assets(self):
        return {key for a in self.broker.accounts.values() for key in a.positions} | {
            key for learner in self.learners.values() for key in learner.retained_assets()} | {
            key for key in self.focus_assets.values() if key}

    def record_board(self, board):
        self.board_file.write(json.dumps(board, allow_nan=False) + '\n')

    def record_quote(self, quote):
        self.market_file.write(json.dumps(quote, allow_nan=False) + '\n')
        self.broker.mark({quote['asset_id']: quote})
        for key, account in self.broker.accounts.items():
            history = self.histories[key]
            if not history or quote['received_at'] - history[-1]['time'] >= self.settings['quote_poll_seconds'] - .1:
                history.append({'time': quote['received_at'], 'equity': account.equity()})
        for learner in self.learners.values():
            for pending in learner.pending:
                if pending['asset_id'] == quote['asset_id'] and pending['pair_address'] == quote['pair_address'] and quote['received_at'] > pending['observed_at']:
                    pending['minimum_price'] = min(pending['minimum_price'], quote['price'])

    def state(self):
        now = time.time()
        accounts = self.frozen_accounts or {k: a.public(now, self.settings['quote_max_age_seconds']) for k, a in self.broker.accounts.items()}
        ranks = sorted(self.keys, key=lambda k: (accounts[k]['alive'], accounts[k]['equity']), reverse=True)
        bios = []
        for key in self.keys:
            focus = self.focus_assets[key]
            market = self.market.quotes.get(focus)
            charts = {a: [{'time': q['received_at'], 'price': q['price']} for q in self.market.histories[a]]
                      for a in set(self.broker.accounts[key].positions) | ({focus} if focus else set())}
            bios.append({'id': key, 'activity': self.activities[key].current, 'metadata': self.metadata[key], 'account': accounts[key],
                         'rank': ranks.index(key) + 1, 'telemetry': self.telemetry[key],
                         'history': list(self.histories[key]), 'training': self.learners[key].summary(),
                         'focus_asset_id': focus, 'market': market, 'market_fresh': bool(focus and self.market.quote_fresh(focus)),
                         'market_history': charts.get(focus, []), 'asset_histories': charts,
                         'selection': self.selections[key], 'max_positions': self.broker.limit,
                         'decision_clock': {'phase': self.phases[key] if accounts[key]['alive'] else 'out',
                            'next_at': self.schedule.effective_due(key) if accounts[key]['alive'] else None,
                            'interval_seconds': self.schedule.interval, 'jitter_seconds': self.schedule.jitter}})
        assets = [{**asset, 'quote': self.market.quotes.get(key), 'fresh': self.market.quote_fresh(key),
                   'in_trending': key in self.market.candidates and self.market.board_fresh(),
                   'entry_problem': self.market.entry_problem(key)} for key, asset in self.market.assets.items()]
        return {'run_id': self.run_id, 'competitors': self.keys, 'mode': 'paper', 'market_mode': 'fomo_trending',
                'status': self.status, 'paused': self.paused, 'server_time': now,
                'started_at': self.started_at, 'ended_at': self.ended_at, 'sequence': self.sequence,
                'market': self.market.latest, 'market_fresh': self.market.fresh(),
                'market_error': self.market.error or self.market.discovery_error,
                'market_history': [], 'error': self.error, 'bios': bios, 'assets': assets,
                'recent_decisions': list(self.recent),
                'rules': {**{k: self.config[k] for k in ['initial_cash', 'round_seconds', 'stop_equity_fraction',
                            'tick_seconds', 'simulated_ms', 'readout_threshold']},
                          'fee_bps': self.settings['fee_bps'], 'slippage_bps': self.settings['slippage_bps'],
                          'cooldown_seconds': self.settings['trade_cooldown_seconds'],
                          'max_positions': self.broker.limit, 'live_max_positions': self.settings['live_max_positions'],
                          'network_cost_usd': self.settings['network_cost_usd'],
                          'quote_max_age_seconds': self.settings['quote_max_age_seconds']},
                'fomo': {'platform': 'https://fomo.family/', 'status': 'discovery_connected' if self.market.board_fresh() else 'discovery_waiting',
                         'accounts': len(self.keys), 'execution': 'not_connected', 'board': 'Trending',
                         'candidate_count': len(self.market.candidates), 'board_observed_at': self.market.board_at,
                         'complete_board': False}}

    def selection_keys(self, bio):
        account, learner = self.broker.accounts[bio], self.learners[bio]
        held = [k for k in account.positions if self.market.quote_fresh(k)]
        available = [k for k in self.market.candidates if k not in account.positions and self.market.quote_fresh(k)]
        learner.random.shuffle(available)
        available.sort(key=lambda k: self.reviewed[bio].get(k, 0.0))
        return held + available[:self.settings['new_candidates_per_check']]

    def evaluate(self, bio, quote, features, neural):
        account, learner = self.broker.accounts[bio], self.learners[bio]
        asset = quote['asset_id']
        position = account.positions.get(asset)
        equity = account.equity()
        value = min(equity * self.settings['allocation_fraction'],
                    quote['liquidity_usd'] * self.settings['max_pool_fraction'],
                    quote['volume_5m_usd'] * self.settings['max_volume_fraction'])
        costs = cost_bps(self.settings, quote, max(self.settings['minimum_trade_value'], value)) or 10000.
        vector = model_features(neural, features, quote, costs)
        bootstrap = neural['score'] * 180 + math.tanh(quote['change_5m_pct'] / 5) * 180 - costs
        prediction = learner.estimate(vector) if learner.active_version else bootstrap
        entry_problem = self.market.entry_problem(asset)
        prices = [q['price'] for q in self.market.histories[asset]]
        move = math.log(prices[-1] / prices[0]) * 10000 if prices else 0.
        range_bps = (max(prices) / min(prices) - 1) * 10000 if prices else 0.
        action, reason, risk = 'HOLD', 'Expected advantage does not clear the entry threshold', False
        if position:
            pnl = position.quantity * quote['price'] / position.cost_basis - 1
            if account.liquidating or pnl <= -self.settings['position_stop_fraction']:
                action, reason, risk = 'SELL', 'Portfolio risk exit' if account.liquidating else 'Position drawdown limit reached', True
            elif time.time() - position.opened_at >= self.settings['minimum_hold_seconds']:
                if (learner.active_version and prediction < -self.settings['exit_margin_bps']) or (
                    not learner.active_version and neural['score'] < -.25 and quote['change_5m_pct'] < 0):
                    action, reason = 'SELL', 'This brain estimates a weaker holding opportunity'
                else:
                    reason = 'Keep this position while the exit signal remains weak'
            else:
                reason = 'Allowing the new position time to develop'
        elif entry_problem:
            reason = entry_problem
        elif features['history_samples'] < self.settings['bio_warmup_observations']:
            reason = 'Building this brain’s observations of this token'
        elif prediction > self.settings['entry_margin_bps']:
            action, reason = 'BUY', 'This brain’s estimated advantage clears the entry threshold'
        if action == 'BUY' and len(account.positions) >= self.broker.limit:
            action, reason = 'HOLD', 'Maximum simultaneous positions reached'
        if action != 'HOLD' and not risk and time.time() - account.last_trade_ts < self.settings['trade_cooldown_seconds']:
            action, reason = 'HOLD', 'Waiting before the next portfolio trade'
        fraction = position.quantity * quote['price'] / max(equity, 1e-9) if position else 0.
        return {'asset_id': asset, 'chain': quote['chain'], 'address': quote['address'], 'symbol': quote['symbol'],
                'action': action, 'reason': reason, 'risk_exit': risk, 'neural_score': neural['score'],
                'prediction_net_bps': prediction, 'model_version': learner.active_version,
                'model_kind': 'validated linear readout' if learner.active_version else 'untrained neural/momentum prior',
                'round_trip_cost_bps': costs, 'vector': vector, 'entry_problem': entry_problem,
                'held': bool(position), 'position_fraction': fraction, 'recent_move_bps': move,
                'recent_range_bps': range_bps, 'history_samples': features['history_samples'],
                'allocation_fraction': self.settings['allocation_fraction'], 'exploration': False,
                'exploration_draw': None}

    def choose(self, bio, evaluations):
        learner, account = self.learners[bio], self.broker.accounts[bio]
        exits = [e for e in evaluations if e['action'] == 'SELL']
        if exits:
            return max(exits, key=lambda e: (e['risk_exit'], -e['prediction_net_bps']))
        entries = [e for e in evaluations if e['action'] == 'BUY']
        if entries:
            return max(entries, key=lambda e: e['prediction_net_bps'])
        candidates = [e for e in evaluations if not e['held'] and e['entry_problem'] is None
                      and e['history_samples'] >= self.settings['bio_warmup_observations']]
        draw = learner.random.random()
        if candidates and len(account.positions) < self.broker.limit and not account.liquidating and (
            time.time() - account.last_trade_ts >= self.settings['trade_cooldown_seconds']) and draw < self.settings['learning']['paper_exploration_probability']:
            selected = learner.random.choice(candidates)
            selected.update(action='BUY', reason='Small paper exploration to observe a new opportunity',
                            allocation_fraction=self.settings['learning']['exploration_fraction'],
                            exploration=True, exploration_draw=draw,
                            exploration_probability=self.settings['learning']['paper_exploration_probability'] / len(candidates))
            return selected
        selected = max(evaluations, key=lambda e: (e['held'], e['prediction_net_bps']))
        selected['exploration_draw'] = draw
        return selected

    def mature(self, bio, now):
        learner = self.learners[bio]
        for outcome in learner.observe(self.market.quotes, now, self.settings['quote_max_age_seconds']):
            self.db.execute('INSERT INTO experiences VALUES (?,?,?,?)',
                            (outcome['id'], bio, outcome['observed_at'], json.dumps(outcome, allow_nan=False)))
        for event in learner.events:
            self.db.execute('INSERT INTO model_events VALUES (?,?,?,?)',
                            (f'{bio}:{event["version"]}', bio, event['evaluated_at'], json.dumps(event, allow_nan=False)))
        learner.events.clear()
        previous = self.pending_accounts.pop(bio, None)
        account = self.broker.accounts[bio]
        if previous:
            outcome = {**previous, 'observed_at': now, 'equity_after': account.equity(),
                       'net_return_bps': (account.equity() / previous['equity_before'] - 1) * 10000,
                       'valuation_stale': account.public(now, self.settings['quote_max_age_seconds'])['valuation_stale'],
                       'label_kind': 'actual paper portfolio net equity change; no additional cost subtraction'}
            self.db.execute('INSERT INTO account_outcomes VALUES (?,?,?,?)',
                            (outcome['decision_id'], bio, now, json.dumps(outcome, allow_nan=False)))

    async def run(self):
        try:
            await asyncio.gather(*[asyncio.wrap_future(p.submit(bool, True)) for p in self.pools.values()])
            self.status = 'waiting_market'
            await self.recovery_checkpoint()
            while not self.closed:
                if self.paused:
                    self.status = 'paused'
                    await asyncio.sleep(.25)
                    continue
                if not self.market.fresh():
                    self.status = 'waiting_market'
                    await asyncio.sleep(.5)
                    continue
                if self.started_at is None:
                    self.started_at = time.time()
                    self.schedule.start(self.started_at)
                if self.time_limit_reached(time.time()) or not any(a.alive for a in self.broker.accounts.values()):
                    self.finish()
                    break
                self.status = 'running'
                bio = self.schedule.ready(time.time(), [k for k in self.keys if self.broker.accounts[k].alive])
                if bio is None:
                    await asyncio.sleep(.1)
                    continue
                timing = self.schedule.dispatch(bio, time.time())
                self.mature(bio, time.time())
                keys = self.selection_keys(bio)
                if not keys:
                    self.phases[bio] = 'waiting'
                    self.schedule.completed(time.time())
                    self.db.commit()
                    continue
                self.phases[bio] = 'thinking'
                observations, evaluations = {}, []
                for asset in keys:
                    if not self.market.quote_fresh(asset):
                        continue
                    quote = dict(self.market.quotes[asset])
                    if self.encoder_pairs[bio].get(asset) != quote['pair_address']:
                        self.encoders[bio][asset] = FeatureEncoder(self.config)
                        self.encoder_pairs[bio][asset] = quote['pair_address']
                    features = self.encoders[bio][asset].encode(quote)
                    neural = await asyncio.wait_for(asyncio.wrap_future(self.pools[bio].submit(advance, features)), 30)
                    evaluated_at = time.time()
                    evaluation = self.evaluate(bio, quote, features, neural)
                    observation_id = f'{self.run_id}:observation:{bio}:{neural["sequence"]}'
                    evaluation['observation_id'] = observation_id
                    self.reviewed[bio][asset] = evaluated_at
                    observations[asset] = (quote, features, neural)
                    evaluations.append(evaluation)
                    compact = {'id': observation_id, 'bio_id': bio, 'evaluated_at': evaluated_at,
                               'brain_sequence': neural['sequence'], 'input_quote': quote, 'features': features,
                               'readout_rates': neural['readout_rates'], 'counts_sha256': neural['counts_sha256'],
                               'neural_score': neural['score'], 'evaluation': dict(evaluation)}
                    self.db.execute('INSERT INTO observations VALUES (?,?,?,?)',
                                    (observation_id, bio, evaluated_at, json.dumps(compact, allow_nan=False)))
                    if evaluation['round_trip_cost_bps'] < 3000 and len(self.market.histories[asset]) >= self.settings['warmup_quotes']:
                        self.learners[bio].watch(observation_id, quote, evaluation['vector'], evaluation['round_trip_cost_bps'], evaluated_at)
                if not evaluations:
                    self.schedule.completed(time.time())
                    self.phases[bio] = 'waiting'
                    continue
                chosen = self.choose(bio, evaluations)
                asset = chosen['asset_id']
                quote, features, neural = observations[asset]
                self.focus_assets[bio] = asset
                self.selections[bio] = [{k: v for k, v in e.items() if k != 'vector'} for e in evaluations]
                completed = time.time()
                self.sequence += 1
                decision_id = f'{self.run_id}:{self.sequence}:{bio}'
                account = self.broker.accounts[bio]
                policy = {'version': ReadoutLearner.VERSION, 'mode': self.learners[bio].summary()['mode'],
                          'action': chosen['action'], 'neural_action': neural['action'], 'reason': chosen['reason'],
                          'target_position_fraction': chosen['position_fraction'] if chosen['action'] == 'HOLD' else 0 if chosen['action'] == 'SELL' else chosen['allocation_fraction'],
                          'candidate_target_fraction': chosen['allocation_fraction'], 'position_fraction': chosen['position_fraction'],
                          'signal_strength': abs(neural['score']), 'confirmation_count': 0, 'context_samples': chosen['history_samples'],
                          'recent_move_bps': chosen['recent_move_bps'], 'recent_range_bps': chosen['recent_range_bps'],
                          'estimated_round_trip_cost_bps': chosen['round_trip_cost_bps'],
                          'prediction_net_bps': chosen['prediction_net_bps'], 'model_version': chosen['model_version'],
                          'model_kind': chosen['model_kind'], 'exploration': chosen['exploration'],
                          'exploration_draw': chosen['exploration_draw']}
                intent = {'id': decision_id, 'bio_id': bio, 'asset_id': asset, 'created_at': completed,
                          'action': chosen['action'], 'reason': chosen['reason'],
                          'allocation_fraction': chosen['allocation_fraction'], 'sell_fraction': 1., 'risk_exit': chosen['risk_exit']}
                self.pending_accounts[bio] = {'decision_id': decision_id, 'bio_id': bio, 'asset_id': asset,
                                              'equity_before': account.equity(), 'created_at': completed}
                fill_quote = None
                fill = {'status': 'held', 'reason': chosen['reason'], 'intent_id': decision_id,
                        'bio_id': bio, 'asset_id': asset, 'symbol': quote['symbol'], 'action': chosen['action']}
                if chosen['action'] != 'HOLD':
                    self.phases[bio] = 'settling'
                    try:
                        fill_quote = await self.market.after(asset, completed)
                    except asyncio.TimeoutError:
                        fill.update(status='unfilled', reason='No new price observation for this contract')
                    if fill_quote:
                        if self.paused:
                            fill['reason'] = 'Operator paused before settlement'
                        else:
                            fill = self.broker.execute(intent, fill_quote, entry_allowed=self.market.entry_problem(asset) is None)
                timing['completed_at'] = completed
                result = {**neural, 'id': decision_id, 'run_id': self.run_id,
                          'event_sequence': self.sequence, 'market_sequence': self.sequence,
                          'created_at': completed, 'asset': {k: quote[k] for k in ['asset_id', 'chain', 'address', 'symbol', 'url']},
                          'neural_action': neural['action'], 'action': chosen['action'], 'reason': chosen['reason'],
                          'policy': policy, 'input_quote': quote, 'features': features,
                          'execution_quote': fill_quote, 'fill': fill, 'schedule': timing,
                          'selection': self.selections[bio], 'intent': intent,
                          'account': account.public(max_age=self.settings['quote_max_age_seconds']),
                          'training': self.learners[bio].summary()}
                self.telemetry[bio] = result
                self.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',
                                (decision_id, self.sequence, bio, completed, json.dumps(result, allow_nan=False)))
                if fill['status'] == 'filled':
                    self.db.execute('INSERT INTO fills VALUES (?,?,?)', (decision_id, fill['timestamp'], json.dumps(fill, allow_nan=False)))
                self.recent.appendleft({k: result[k] for k in ['id', 'bio_id', 'created_at', 'action', 'score', 'spikes', 'fill', 'asset']})
                self.db.commit()
                self.save_models()
                self.schedule.completed(time.time())
                self.phases[bio] = 'waiting'
                for key in set(self.encoders[bio]) - set(self.market.assets):
                    self.encoders[bio].pop(key, None)
                    self.encoder_pairs[bio].pop(key, None)
                    self.reviewed[bio].pop(key, None)
                await self.recovery_checkpoint()
                if self.sequence % 100 == 0:
                    await self.checkpoint()
            await self.checkpoint()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.status, self.error = 'error', f'{type(exc).__name__}: {exc}'
            (self.run_dir / 'error.txt').write_text(self.error)
        finally:
            if self.status in ('finished', 'error'):
                self.tasks[0].cancel()

    def save_models(self):
        directory = self.run_dir / 'models'
        directory.mkdir(exist_ok=True)
        for key, learner in self.learners.items():
            temporary = directory / f'{key}.tmp'
            temporary.write_text(json.dumps(learner.checkpoint(), allow_nan=False))
            temporary.replace(directory / f'{key}.json')

    async def checkpoint(self):
        folder = self.run_dir / 'checkpoints' / str(self.sequence)
        folder.mkdir(parents=True, exist_ok=True)
        await asyncio.gather(*[asyncio.wrap_future(p.submit(save_checkpoint, str(folder))) for p in self.pools.values()])
        (folder / 'portfolios.json').write_text(json.dumps({k: asdict(a) for k, a in self.broker.accounts.items()}, allow_nan=False))
        self.save_models()

    def finish(self):
        self.status, self.ended_at = 'finished', time.time()
        self.frozen_accounts = {k: a.public(self.ended_at, self.settings['quote_max_age_seconds']) for k, a in self.broker.accounts.items()}
        (self.run_dir / 'result.json').write_text(json.dumps({'run_id': self.run_id,
            'ended_at': self.ended_at, 'accounts': self.frozen_accounts,
            'settlement': 'last observed marks; positions retained; no fictitious liquidation'}, allow_nan=False))

    async def stop(self):
        self.closed = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            if self.paused and self.status == 'paused' and all(p == 'waiting' for p in self.phases.values()):
                self.db.commit()
                await self.recovery_checkpoint()
            # Only the previously published decision boundary is eligible for recovery.
            (self.run_dir / 'stopped_state.json').write_text(json.dumps(self.state(), allow_nan=False))
        finally:
            for pool in self.pools.values():
                pool.shutdown(wait=True, cancel_futures=True)
            self.db.close()
            self.market_file.close()
            self.board_file.close()
