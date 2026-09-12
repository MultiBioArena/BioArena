"""Durable execution of Bio decisions in a separate process.

The paper engine remains the decision source. Its cash, fills and exploration
are never treated as real account evidence. This module has no network access.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from .execution_preflight import usd
from .meme_market import address_key
from .registry import validate_bio_id


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


@dataclass(frozen=True)
class ExecutionLimits:
    buy_usd: str = '2'
    max_buy_usd: str = '10'
    max_fee_usd: str = '0.30'
    max_fee_bps: int | None = 300
    max_price_impact_bps: int = 200
    max_slippage_bps: int | None = None
    max_positions: int = 1
    allow_exploration: bool = False
    sell_cooldown_seconds: int | None = None
    decision_age_seconds: int = 45
    cooldown_seconds: int = 120
    max_buys_per_day: int = 6
    max_daily_buy_usd: str = '20'
    acknowledge_network_fee: bool = False

    def __post_init__(self):
        if not Decimal('2') <= usd(self.buy_usd) <= usd(self.max_buy_usd) <= 10:
            raise ValueError('Buy size must be between 2 USD and the 10 USD ceiling')
        if not 0 < usd(self.max_fee_usd) <= 2 or usd(self.max_daily_buy_usd) < usd(self.buy_usd):
            raise ValueError('Invalid fee or daily spending limit')
        for key, low, high in [('max_fee_bps', 1, 10000), ('max_price_impact_bps', 1, 1000),
                               ('max_slippage_bps', 1, 3000), ('max_positions', 1, 2),
                               ('sell_cooldown_seconds', 0, 3600),
                               ('decision_age_seconds', 1, 60), ('cooldown_seconds', 30, 3600),
                               ('max_buys_per_day', 1, 100)]:
            value = getattr(self, key)
            if value is None and key in ('max_fee_bps', 'max_slippage_bps', 'sell_cooldown_seconds'):
                continue
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'Invalid {key}')
        if type(self.acknowledge_network_fee) is not bool:
            raise ValueError('Network fee acknowledgment must be a boolean')
        if type(self.allow_exploration) is not bool:
            raise ValueError('Exploration selection must be a boolean')


class ExecutionStore:
    """Commit an attempt before entering the browser; an interrupted attempt locks.

    A blocked/pre-click result can terminate safely. Any uncertain post-click
    outcome stays unresolved. There is deliberately no blind retry/reset command.
    """
    def __init__(self, path, mode, bindings, limits, *, identities=None):
        if mode not in ('shadow', 'live'):
            raise ValueError('Choose shadow or live')
        if not bindings or len(set(bindings.values())) != len(bindings):
            raise ValueError('Every Bio needs a distinct account')
        for bio, account in bindings.items():
            validate_bio_id(bio)
            if not isinstance(account, str) or not account:
                raise ValueError('Missing account reference')
        if str(path) != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS orders(
                id TEXT PRIMARY KEY, bio TEXT, account TEXT, at REAL, action TEXT,
                asset TEXT, fingerprint TEXT, status TEXT, intent TEXT, evidence TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_pending ON orders(account)
                WHERE status IN ('attempting','unknown');
            CREATE TABLE IF NOT EXISTS holdings(
                account TEXT, asset TEXT, raw_quantity TEXT, decimals INTEGER,
                opened_at REAL, buy_id TEXT, PRIMARY KEY(account,asset));
        ''')
        with self.db:
            # Prevent a shadow journal from becoming a live journal, or rebinding a
            # funded account by editing its configuration after a restart.
            pinned = [('mode', mode), ('bindings', encoded(bindings))]
            if identities is not None:
                pinned.append(('custody_identity_sha256', hashlib.sha256(encoded(identities).encode()).hexdigest()))
            for key, value in pinned:
                old = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
                if old and old[0] != value:
                    raise ValueError('Journal mode/account binding is immutable')
                self.db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)', (key, value))
            columns = list(self.db.execute('PRAGMA table_info(holdings)'))
            if [row[1] for row in columns if row[5]] == ['account']:
                self.db.execute('ALTER TABLE holdings RENAME TO holdings_single')
                self.db.execute('''CREATE TABLE holdings(account TEXT,asset TEXT,raw_quantity TEXT,
                    decimals INTEGER,opened_at REAL,buy_id TEXT,PRIMARY KEY(account,asset))''')
                self.db.execute('INSERT INTO holdings SELECT * FROM holdings_single')
                self.db.execute('DROP TABLE holdings_single')
        self.mode, self.bindings, self.limits = mode, bindings, limits

    def holdings(self, bio):
        return [dict(zip(('asset_id', 'raw_quantity', 'decimals', 'opened_at', 'buy_id'), row))
                for row in self.db.execute('SELECT asset,raw_quantity,decimals,opened_at,buy_id FROM holdings WHERE account=? ORDER BY opened_at,asset',
                                           (self.bindings[bio],))]

    def holding(self, bio, asset_id=None):
        return next((p for p in self.holdings(bio) if asset_id is None or p['asset_id'] == asset_id), None)

    def pending(self, bio):
        return self.db.execute("SELECT id,status FROM orders WHERE account=? AND status IN ('attempting','unknown')",
                               (self.bindings[bio],)).fetchone()

    def status(self, intent_id):
        row = self.db.execute('SELECT status FROM orders WHERE id=?', (intent_id,)).fetchone()
        return row[0] if row else None

    def make_intent(self, decision, now):
        bio = validate_bio_id(decision['bio_id'])
        if bio not in self.bindings:
            return None, 'Bio has no execution binding'
        if self.status(decision['id']):
            return None, 'Decision already consumed'
        age = now - decision['created_at']
        if not math.isfinite(age) or not 0 <= age <= self.limits.decision_age_seconds:
            return None, 'Decision expired'
        action = decision['action']
        if action == 'HOLD':
            return None, 'Bio chose HOLD'
        if action not in ('BUY', 'SELL') or decision['intent']['action'] != action:
            raise ValueError('Invalid or inconsistent Bio action')
        asset = decision['asset']
        chain, address = asset['chain'], address_key(asset['chain'], asset['address'])
        asset_id = f'{chain}:{address}'
        if asset_id != asset['asset_id'] or asset_id != decision['intent']['asset_id']:
            raise ValueError('Decision contract identity mismatch')
        if self.pending(bio):
            return None, 'Account locked by an unresolved order'
        positions = self.holdings(bio)
        holding = self.holding(bio, asset_id)
        policy = decision['policy']
        if action == 'BUY':
            if policy.get('exploration') is not False and not (self.limits.allow_exploration and policy.get('exploration') is True):
                return None, 'Paper exploration is excluded from live execution'
            if holding or len(positions) >= self.limits.max_positions:
                return None, 'One holding per Bio; adding or switching is blocked' if self.limits.max_positions == 1 else 'Live position capacity reached or token already held'
            since = int(now // 86400) * 86400
            rows = self.db.execute("SELECT intent FROM orders WHERE account=? AND action='BUY' AND at>=? AND status IN ('filled','attempting','unknown')",
                                   (self.bindings[bio], since)).fetchall()
            total = sum((usd(json.loads(row[0])['amount_usd']) for row in rows), Decimal(0))
            if len(rows) >= self.limits.max_buys_per_day or total + usd(self.limits.buy_usd) > usd(self.limits.max_daily_buy_usd):
                return None, 'Daily entry budget reached'
        elif not holding or holding['asset_id'] != asset_id:
            return None, 'No matching executor-owned position to sell'
        last = self.db.execute("SELECT MAX(at) FROM orders WHERE account=? AND status='filled'", (self.bindings[bio],)).fetchone()[0]
        cooldown = self.limits.sell_cooldown_seconds if action == 'SELL' and self.limits.sell_cooldown_seconds is not None else self.limits.cooldown_seconds
        if last is not None and now - last < cooldown and not (action == 'SELL' and decision['intent'].get('risk_exit') is True):
            return None, 'Execution cooldown'
        intent = {'id': decision['id'], 'bio_id': bio, 'account_ref': self.bindings[bio],
                  'action': action, 'chain': chain, 'address': address, 'asset_id': asset_id,
                  'created_at': decision['created_at'], 'source_sha256': hashlib.sha256(encoded(decision).encode()).hexdigest(),
                  'model_version': policy.get('model_version'), 'reason': decision['reason'],
                  'limits': asdict(self.limits), 'known_positions': positions}
        if action == 'BUY':
            intent['amount_usd'] = self.limits.buy_usd
        else:
            intent.update(quantity_raw=holding['raw_quantity'], decimals=holding['decimals'], entry_id=holding['buy_id'])
        return intent, None

    def claim(self, intent, now):
        fingerprint = hashlib.sha256(encoded(intent).encode()).hexdigest()
        with self.db:
            old = self.db.execute('SELECT fingerprint FROM orders WHERE id=?', (intent['id'],)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise ValueError('Decision ID reused with different content')
                return False
            self.db.execute('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)',
                (intent['id'], intent['bio_id'], intent['account_ref'], now, intent['action'], intent['asset_id'],
                 fingerprint, 'attempting', encoded(intent), '{}'))
        return True

    def finish(self, intent, evidence):
        status = evidence.get('status')
        if status not in ('blocked', 'shadow', 'filled', 'unknown'):
            status = 'unknown'
        if evidence.get('clicked') is not False and status in ('blocked', 'shadow'):
            status = 'unknown'
        if self.mode == 'shadow' and (evidence.get('clicked') is not False or status == 'filled'):
            status = 'unknown'
        if status == 'filled':
            # A platform success message alone cannot close an order.
            if not self._valid_fill(intent, evidence):
                status = 'unknown'
        with self.db:
            row = self.db.execute('SELECT status,intent FROM orders WHERE id=?', (intent['id'],)).fetchone()
            if not row or row[1] != encoded(intent) or row[0] not in ('attempting', 'unknown'):
                raise ValueError('Order cannot be finalized with this evidence')
            self.db.execute('UPDATE orders SET status=?,evidence=? WHERE id=?', (status, encoded(evidence), intent['id']))
            if status == 'filled':
                if intent['action'] == 'BUY':
                    p = evidence['position_after']
                    self.db.execute('INSERT INTO holdings VALUES (?,?,?,?,?,?)',
                        (intent['account_ref'], intent['asset_id'], p['raw_quantity'], p['decimals'], evidence['observed_at'], intent['id']))
                else:
                    self.db.execute('DELETE FROM holdings WHERE account=? AND asset=?', (intent['account_ref'], intent['asset_id']))
        return status

    @staticmethod
    def _valid_fill(intent, evidence):
        native = evidence.get('solana_evidence') or {}
        if not isinstance(native, dict):
            return False
        native_verified = (intent.get('chain') == 'solana' and evidence.get('settlement_provider') == 'solana'
                           and native.get('commitment') == 'confirmed' and native.get('owner_balances_verified') is True
                           and type(native.get('slot')) is int and native['slot'] > 0
                           and isinstance(native.get('signature'), str)
                           and re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{64,88}', native['signature']) is not None
                           and native['signature'] == evidence.get('route_id'))
        provider = evidence.get('settlement_provider')
        verified = native_verified if provider == 'solana' else provider in (None, 'relay') and evidence.get('relay_status') == 'SUCCESS'
        if (evidence.get('clicked') is not True or not verified
                or not evidence.get('route_id') or evidence.get('account_ref') != intent['account_ref']
                or evidence.get('asset_id') != intent['asset_id'] or evidence.get('action') != intent['action']
                or evidence.get('balances_verified') is not True):
            return False
        at = evidence.get('observed_at')
        if not isinstance(at, (int, float)) or not math.isfinite(at) or at < intent['created_at']:
            return False
        p = evidence.get('position_after')
        if provider == 'solana':
            try:
                cash = Decimal(native['cash_delta_raw'])
                if cash != Decimal(str(evidence['cash_delta_usd']))*1_000_000 or cash == 0:
                    return False
                delta = int(native['token_delta_raw'])
                if intent['action'] == 'SELL':
                    if cash <= 0 or delta != -int(intent['quantity_raw']):
                        return False
                elif cash >= 0 or not isinstance(p, dict) or delta != int(p['raw_quantity']):
                    return False
            except (KeyError, ValueError, TypeError, ArithmeticError):
                return False
        if intent['action'] == 'SELL':
            return p is None
        return (isinstance(p, dict) and p.get('asset_id') == intent['asset_id']
                and isinstance(p.get('raw_quantity'), str) and p['raw_quantity'].isdigit()
                and int(p['raw_quantity']) > 0 and type(p.get('decimals')) is int and 0 <= p['decimals'] <= 36)

    def report(self):
        return {'mode': self.mode, 'limits': asdict(self.limits),
                'accounts': {bio: {'pending': self.pending(bio), 'holding': self.holding(bio), 'holdings': self.holdings(bio)} for bio in self.bindings},
                'counts': dict(self.db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))}

    def close(self):
        self.db.close()


class AutoExecutor:
    def __init__(self, store, adapter, *, clock=time.time, enabled=lambda: True, trial_id=None, source_kind='bio_policy'):
        self.store, self.adapter, self.clock, self.enabled = store, adapter, clock, enabled
        self.trial_id = trial_id
        if source_kind not in ('bio_policy','operator_execution_check'):
            raise ValueError('Unknown execution source')
        self.source_kind = source_kind

    def process(self, decision):
        if not self.enabled():
            return {'status': 'held', 'reason': 'Execution is stopped'}
        intent, reason = self.store.make_intent(decision, self.clock())
        if intent is None:
            return {'status': 'held', 'reason': reason}
        if self.trial_id is not None:
            intent['trial_id'] = self.trial_id
        intent['source_kind'] = 'live_position_exit' if decision.get('policy',{}).get('exit_manager') is True else self.source_kind
        if not self.store.claim(intent, self.clock()):
            return {'status': 'held', 'reason': 'Decision already consumed'}
        try:
            if not self.enabled():
                evidence = {'status': 'blocked', 'clicked': False, 'reason': 'Execution stopped before browser entry'}
            else:
                evidence = self.adapter.execute(intent, self.store.limits, live=self.store.mode == 'live')
                if not isinstance(evidence, dict):
                    raise ValueError('Malformed execution evidence')
                encoded(evidence)
        except Exception:
            # A transport timeout can occur after the website accepted the order.
            evidence = {'status': 'unknown', 'reason': 'Browser transport interrupted; account requires reconciliation'}
        status = self.store.finish(intent, evidence)
        return {'id': intent['id'], 'bio_id': intent['bio_id'], 'status': status, 'evidence': evidence}
