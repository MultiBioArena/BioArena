"""Allowlisted public observations of execution; never drive accounts or orders."""
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time

from .registry import DEFAULT_BIOS, validate_bio_id
from .fomo_networks import valid_token_path


ROOT = Path(__file__).resolve().parents[2]
PHASES = {'waiting_buy', 'waiting_sell', 'managing_positions', 'closing_positions', 'complete', 'expired', 'review_required'}
ORDER_STATES = {'attempting', 'unknown', 'blocked', 'filled', 'shadow'}


def finite(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def asset(value):
    if not isinstance(value, str) or not valid_token_path('/tokens/'+value.replace(':','/')):
        return None
    chain,address = value.split(':')
    address = address if chain == 'solana' else address.lower()
    return {'asset_id': chain+':'+address, 'chain': chain, 'address': address}


def reason_code(value):
    # Never publish arbitrary browser errors, profile names or private paths.
    reasons = {
        'Quoted fees exceed configured limits': 'fee_limit',
        'Quoted price impact exceeds configured limit': 'impact_limit',
        'Quoted slippage exceeds configured limit': 'slippage_limit',
        'This adapter currently supports Robinhood tokens only': 'unsupported_chain',
        'Unsupported FOMO network': 'unsupported_chain',
        'Platform requires attention or blocks trading': 'platform_block',
        'Trade submit button is ambiguous': 'trade_form_block',
        'Insufficient cash with fee reserve': 'cash_limit',
        'Bio decision expired during preparation': 'expired_signal',
        'Daily entry budget reached': 'entry_budget',
        'Execution cooldown': 'cooldown',
        'Paper exploration is excluded from live execution': 'paper_exploration',
        'Bio chose HOLD': 'hold',
        'Signal does not match the current trial leg or held token': 'trial_filter',
        'No matching executor-owned position to sell': 'position_mismatch',
        'One holding per Bio; adding or switching is blocked': 'position_limit',
        'Live position capacity reached or token already held': 'position_limit',
    }
    return reasons.get(value, 'execution_check') if value else None


def policy_counts(value, ids):
    result = {}
    for bio in ids:
        if bio not in (value or {}):
            continue
        row = (value or {}).get(bio, {})
        if not isinstance(row, dict):
            continue
        counts = {}
        for group, keys in [('actions',('BUY','SELL','HOLD')),
                            ('outcomes',('filtered','held','blocked','shadow','filled','unknown'))]:
            source = row.get(group) or {}
            counts[group] = {key:source[key] for key in keys
                             if type(source.get(key)) is int and source[key]>=0}
        reasons = {}
        for reason, count in (row.get('reasons') or {}).items():
            if type(count) is int and count>=0:
                key = reason_code(reason)
                reasons[key] = reasons.get(key,0)+count
        result[bio] = {**counts, 'reasons':reasons}
    return result


def public_snapshot(directory=None, now=None):
    directory = Path(directory or os.environ.get('BIO_ARENA_EXECUTION_DIR', ROOT/'.private/execution'))
    now = time.time() if now is None else now
    result = {'as_of': now, 'available': False, 'fresh': False, 'running': False,
              'executor_state': 'not_started', 'updated_at': None, 'trial': None,
              'limits': None, 'bios': [], 'orders': [], 'orders_truncated': False,
              'execution_kind': 'bio_policy', 'check_stage': None, 'policy_audit': {},
              'scope': 'FOMO-reported fills and account deltas; independent chain finality is unverified'}
    report_path, database = directory/'live-status.json', directory/'live.sqlite'
    if not report_path.exists() and not database.exists():
        return result
    try:
        report = json.loads(report_path.read_text())
        if report.get('mode') != 'live' or not isinstance(report.get('accounts'), dict):
            raise ValueError('Invalid execution report')
        updated = finite(report.get('updated_at'))
        if updated is None:
            raise ValueError('Missing report timestamp')
        # A browser attempt can spend up to 110 seconds awaiting a response.
        fresh = 0 <= now-updated <= 120
        trial = report.get('trial')
        operator_check = report.get('execution_kind') == 'operator_check'
        check_stage = report.get('check_stage') if operator_check else None
        if check_stage not in (None,'preparing_buy','buy_verified','exit_cooldown','preparing_sell','complete','incomplete','quote_only','stopped'):
            raise ValueError('Unknown acceptance check stage')
        if trial is not None and (not isinstance(trial, dict) or trial.get('phase') not in PHASES):
            raise ValueError('Invalid trial state')
        ids = list(dict.fromkeys([*DEFAULT_BIOS, *report['accounts']]))
        for bio in ids:
            validate_bio_id(bio)
        active = [trial['bio_id']] if trial else []
        if active and active[0] not in report['accounts']:
            raise ValueError('Unbound trial participant')
        running = fresh and report.get('process_running') is True and report.get('live_enabled') is True
        limits = report.get('limits') or {}
        public_limits = {}
        for key in ('buy_usd', 'max_buy_usd', 'max_fee_usd'):
            value = float(limits[key])
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid limit')
            public_limits[key] = value
        public_limits['max_positions'] = limits.get('max_positions',1)
        public_limits['max_fee_pct'] = float(limits['max_fee_bps'])/100 if limits.get('max_fee_bps') is not None else None
        # Open the existing journal read-only. Missing or corrupt files never
        # create a new ledger or turn an unverified observation into an empty account.
        db = sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True, timeout=1)
        try:
            db.execute('BEGIN')
            mode = db.execute("SELECT value FROM settings WHERE key='mode'").fetchone()
            if mode != ('live',):
                raise ValueError('Journal is not live')
            bindings = json.loads(db.execute("SELECT value FROM settings WHERE key='bindings'").fetchone()[0])
            accounts = []
            for bio in ids:
                account = bindings.get(bio)
                holdings = db.execute('SELECT asset,raw_quantity,decimals FROM holdings WHERE account=? ORDER BY opened_at,asset', (account,)).fetchall()
                pending = db.execute("SELECT status FROM orders WHERE account=? AND status IN ('unknown','attempting')", (account,)).fetchone()
                counts = dict(db.execute('SELECT status,COUNT(*) FROM orders WHERE account=? GROUP BY status', (account,)))
                selected = bio in active
                phase = 'observing' if running and not trial else 'not_enabled'
                if selected:
                    phase = trial['phase'] if running or trial['phase'] not in ('waiting_buy','waiting_sell','managing_positions','closing_positions') else 'stopped'
                    if operator_check and check_stage == 'incomplete':
                        phase = 'check_incomplete'
                if pending:
                    phase = 'submitting' if pending[0] == 'attempting' and running else 'review_required'
                positions = []
                for holding in holdings:
                    identity = asset(holding[0])
                    if not identity or not re.fullmatch(r'\d+', holding[1]) or not 0 <= holding[2] <= 36:
                        raise ValueError('Invalid holding')
                    positions.append({**identity, 'quantity_raw': holding[1], 'decimals': holding[2]})
                accounts.append({'bio_id': bio, 'selected': selected, 'phase': phase,
                    'holding': positions[0] if positions else None, 'holdings': positions, 'verified_fills': counts.get('filled', 0),
                    'blocked_attempts': counts.get('blocked', 0), 'unresolved': bool(pending)})
            orders = []
            for bio, status, action, at, payload, evidence in db.execute(
                    'SELECT bio,status,action,at,intent,evidence FROM orders ORDER BY rowid DESC LIMIT 40'):
                if bio not in ids or status not in ORDER_STATES or action not in ('BUY', 'SELL'):
                    raise ValueError('Invalid order')
                intent, receipt = json.loads(payload), json.loads(evidence)
                quote = receipt.get('quote') or {}
                fee, notional = finite(quote.get('fee_usd')), finite(quote.get('input_usd'))
                orders.append({'bio_id': bio, 'action': action, 'status': status, 'at': finite(at),
                    'source_kind':intent.get('source_kind') if intent.get('source_kind') in ('operator_execution_check','live_position_exit') else 'bio_policy',
                    'asset': asset(intent.get('asset_id')), 'reason_code': reason_code(receipt.get('reason')),
                    'cash_delta_usd': finite(receipt.get('cash_delta_usd')) if status == 'filled' else None,
                    'estimated_fee_usd': fee, 'estimated_fee_pct': fee/notional*100 if fee is not None and notional and notional>0 else None,
                    'balance_verified': status == 'filled' and receipt.get('balances_verified') is True})
            total = db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        finally:
            db.close()
        public_trial = None
        if trial:
            public_trial = {'bio_id': trial['bio_id'], 'phase': trial['phase'],
                'complete': trial.get('complete') is True, 'deadline': finite(trial.get('deadline')),
                'managed_portfolio':trial.get('managed_portfolio') is True,
                'completed_round_trips':trial.get('completed_round_trips'),
                'entry_target_reached':trial.get('entry_target_reached'),
                'cash_change_usd': finite(trial.get('cash_change_usd')) if trial.get('complete') is True else None}
        result.update(available=True, fresh=fresh, running=running, updated_at=updated,
            execution_kind='operator_check' if operator_check else 'bio_policy', check_stage=check_stage,
            policy_audit={} if operator_check else policy_counts(report.get('policy_audit'),ids),
            executor_state='stale' if not fresh else 'running' if running else 'stopped',
            trial=public_trial, limits=public_limits, bios=accounts, orders=orders, orders_truncated=total>len(orders),
            feed_error=bool(report.get('error')))
        return result
    except (OSError, ValueError, TypeError, KeyError, IndexError, sqlite3.Error):
        return {**result, 'executor_state': 'unavailable'}
