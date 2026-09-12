"""Independent delayed-label readouts with chronological shadow validation."""
import math
import random
import numpy as np
from .registry import seed_offset

FEATURE_NAMES = ['bias', 'neural_score', 'buy_rate', 'sell_rate', 'recent_return',
                 'five_minute_change', 'volume', 'volatility', 'liquidity', 'cost']


def model_features(neural, features, quote, costs):
    return [1., neural['score'], math.tanh(neural['readout_rates']['buy'] / 50),
            math.tanh(neural['readout_rates']['sell'] / 50), math.tanh(features['return_bps'] / 100),
            math.tanh(quote['change_5m_pct'] / 10), features['volume'], features['volatility'],
            math.tanh(math.log1p(quote['liquidity_usd']) / 15), math.tanh(costs / 500)]


class ReadoutLearner:
    VERSION = 'delayed-readout-v1'

    def __init__(self, bio, seed, settings):
        self.bio, self.settings = bio, settings
        self.seed = seed + seed_offset(bio, 'learner')
        self.random = random.Random(self.seed)
        self.working = np.zeros(len(FEATURE_NAMES))
        self.active = self.working.copy()
        self.active_version = self.updates = self.candidate_sequence = self.samples = self.expired = 0
        self.candidate = None
        self.pending = []
        self.last_reward = self.updated_at = self.promoted_at = None
        self.events = []

    @staticmethod
    def predict(weights, vector):
        return float(np.clip(np.dot(weights, vector) * 1000, -5000, 5000))

    def estimate(self, vector):
        return self.predict(self.active, vector)

    def watch(self, observation_id, quote, vector, costs, now):
        row = {'id': observation_id, 'bio_id': self.bio, 'asset_id': quote['asset_id'],
               'input_quote_id': quote['id'], 'pair_address': quote['pair_address'],
               'observed_at': now, 'due_at': now + self.settings['label_horizon_seconds'],
               'price_before': quote['price'], 'minimum_price': quote['price'], 'vector': vector,
               'estimated_round_trip_cost_bps': costs, 'active_version': self.active_version,
               'active_prediction_bps': self.estimate(vector),
               'validation_version': None, 'validation_prediction_bps': None}
        if self.candidate and min(now, quote['received_at']) > self.candidate['frozen_at']:
            row['validation_version'] = self.candidate['version']
            row['validation_prediction_bps'] = self.predict(self.candidate['weights'], vector)
        self.pending.append(row)

    def retained_assets(self):
        return {p['asset_id'] for p in self.pending}

    def observe(self, quotes, now, max_age):
        outcomes, remaining = [], []
        for row in self.pending:
            q = quotes.get(row['asset_id'])
            if now > row['due_at'] + self.settings['label_grace_seconds']:
                self.expired += 1
                continue
            if q is None or not 0 <= now - q['received_at'] <= max_age or q['received_at'] <= row['observed_at']:
                remaining.append(row)
                continue
            if q['pair_address'] != row['pair_address']:
                self.expired += 1
                continue
            row['minimum_price'] = min(row['minimum_price'], q['price'])
            if q['received_at'] < row['due_at']:
                remaining.append(row)
                continue
            gross = math.log(q['price'] / row['price_before']) * 10000
            drawdown = max(0., -math.log(row['minimum_price'] / row['price_before']) * 10000)
            reward = gross - row['estimated_round_trip_cost_bps'] - self.settings['downside_penalty'] * drawdown
            target = float(np.clip(reward, -5000, 5000))
            outcome = {**row, 'decision_id': row['id'], 'observed_at': q['received_at'],
                       'input_observed_at': row['observed_at'], 'next_quote_id': q['id'],
                       'market_return_bps': gross, 'drawdown_bps': drawdown, 'reward_bps': reward,
                       'training_target_bps': target, 'target_clipped': reward != target,
                       'label_kind': 'hypothetical long net log return minus downside penalty',
                       'holding_seconds': q['received_at'] - row['observed_at']}
            self._update(outcome, now)
            outcomes.append(outcome)
        self.pending = remaining
        return outcomes

    def _update(self, row, now):
        target, vector = row['training_target_bps'] / 1000, np.asarray(row['vector'], dtype=float)
        if self.candidate and row['validation_version'] == self.candidate['version'] and row['input_observed_at'] > self.candidate['frozen_at']:
            c = self.candidate
            c['count'] += 1
            c['candidate_error'] += (row['validation_prediction_bps'] / 1000 - target) ** 2
            c['active_error'] += (row['active_prediction_bps'] / 1000 - target) ** 2
            c['zero_error'] += target ** 2
        error = float(np.dot(self.working, vector)) - target
        self.working *= 1 - self.settings['learning_rate'] * .001
        self.working -= self.settings['learning_rate'] * error * vector / (1 + float(np.dot(vector, vector)))
        self.updates += 1
        self.samples += 1
        self.last_reward, self.updated_at = row['reward_bps'], now
        if self.candidate and self.candidate['count'] >= self.settings['validation_samples']:
            c = self.candidate
            accepted = c['candidate_error'] < min(c['active_error'], c['zero_error']) * self.settings['validation_improvement']
            event = {k: v for k, v in c.items() if k != 'weights'}
            event.update(evaluated_at=now, accepted=accepted, weights=c['weights'].tolist(),
                         previous_active_version=self.active_version, previous_weights=self.active.tolist(),
                         criterion='future-label squared error vs active and zero baseline; not a profit backtest')
            if accepted:
                self.active = c['weights'].copy()
                self.active_version, self.promoted_at = c['version'], now
            self.events.append(event)
            self.candidate = None
        if self.candidate is None and self.updates >= self.settings['minimum_training_samples']:
            self.candidate_sequence += 1
            self.candidate = {'version': self.candidate_sequence, 'weights': self.working.copy(),
                              'frozen_at': now, 'training_updates': self.updates, 'count': 0,
                              'candidate_error': 0., 'active_error': 0., 'zero_error': 0.}

    def summary(self):
        return {'mode': 'learning' if self.active_version else 'training' if self.updates else 'collecting',
                'policy_version': self.VERSION, 'samples': self.samples, 'updates': self.updates,
                'active_version': self.active_version, 'candidate_version': self.candidate['version'] if self.candidate else None,
                'validation_samples': self.candidate['count'] if self.candidate else 0,
                'validation_required': self.settings['validation_samples'], 'pending_samples': len(self.pending),
                'expired_samples': self.expired, 'last_reward_bps': self.last_reward, 'updated_at': self.updated_at,
                'promoted_at': self.promoted_at, 'horizon_seconds': self.settings['label_horizon_seconds'],
                'algorithm': 'Independent linear readout; delayed labels; chronological shadow validation',
                'scope': 'paper only; fixed connectome; no profit guarantee'}

    def checkpoint(self):
        return {**self.summary(), 'bio_id': self.bio, 'seed': self.seed, 'feature_names': FEATURE_NAMES,
                'working_weights': self.working.tolist(), 'active_weights': self.active.tolist(),
                'random_state': self.random.getstate(), 'pending': self.pending,
                'candidate_sequence': self.candidate_sequence,
                'candidate': {**self.candidate, 'weights': self.candidate['weights'].tolist()} if self.candidate else None}

    def restore(self, payload):
        from .recovery import tuples
        if (payload['bio_id']!=self.bio or payload['seed']!=self.seed
                or payload['policy_version']!=self.VERSION or payload['feature_names']!=FEATURE_NAMES):
            raise ValueError('Readout checkpoint identity or version mismatch')
        for target,source in [('working','working_weights'),('active','active_weights')]:
            weights=np.asarray(payload[source],dtype=float)
            if weights.shape!=(len(FEATURE_NAMES),) or not np.isfinite(weights).all():
                raise ValueError('Invalid readout weights')
            setattr(self,target,weights)
        for target,source in [('updates','updates'),('samples','samples'),('expired','expired_samples'),
                ('active_version','active_version'),('candidate_sequence','candidate_sequence'),
                ('last_reward','last_reward_bps'),('updated_at','updated_at'),('promoted_at','promoted_at')]:
            setattr(self,target,payload[source])
        self.random.setstate(tuples(payload['random_state']))
        self.pending=payload['pending']
        self.candidate=payload['candidate']
        if self.candidate:
            weights=np.asarray(self.candidate['weights'],dtype=float)
            if weights.shape!=(len(FEATURE_NAMES),) or not np.isfinite(weights).all():raise ValueError('Invalid candidate weights')
            self.candidate['weights']=weights
        self.events=[]
