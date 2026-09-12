"""Local decision feed and configuration for the separately started executor."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from .auto_execution import ExecutionLimits, encoded
from .fomo_networks import NETWORKS


def load_config(path, *, live=False):
    config = json.loads(Path(path).read_text())
    if type(config.get('enabled')) is not bool:
        raise ValueError('enabled must explicitly be true or false')
    if live and config['enabled'] is not True:
        raise ValueError('Live execution is disabled in the operator configuration')
    url = urlparse(config['source_url'])
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.query or url.fragment or url.path not in ('','/'):
        raise ValueError('The execution decision feed must be a local HTTP origin')
    limits = ExecutionLimits(**config.get('limits', {}))
    accounts = config['accounts']
    if not isinstance(accounts, dict) or not accounts:
        raise ValueError('Execution accounts are missing')
    for key in ('account_ref','session','browser_directory','profile','user_id','cash_wallet','token_wallet'):
        values = [row.get(key) for row in accounts.values()]
        if any(not isinstance(v,str) or not v for v in values) or len(set(values)) != len(values):
            raise ValueError(f'Account {key} must be configured and distinct')
    for row in accounts.values():
        if type(row.get('enabled')) is not bool:
            raise ValueError('Each account requires an explicit enabled boolean')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',row['profile']) or not re.fullmatch(r'[A-Za-z0-9_-]+',row['user_id']):
            raise ValueError('Invalid pinned profile/user identity')
        if not re.fullmatch(r'0x[0-9a-fA-F]{40}',row['token_wallet']) or not re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}',row['cash_wallet']):
            raise ValueError('Both custody wallets must be configured')
        # Older configurations pinned a single chain. Retain validation of that
        # metadata, while the decision's chain now selects the execution route.
        if 'chain' in row or 'chain_id' in row:
            network = NETWORKS.get(row.get('chain'))
            if not network or row.get('chain_id') != network['balance_id']:
                raise ValueError('Invalid legacy chain metadata')
        row['browser_directory'] = str(Path(row['browser_directory']).resolve())
    if live and not any(row['enabled'] for row in accounts.values()):
        raise ValueError('No account is enabled for live execution')
    # Record exact normalized limits in every report; no untracked defaults.
    config['limits'] = asdict(limits)
    return config, limits


def current_decisions(state, records, now, *, accept_after):
    if (state.get('status') != 'running' or state.get('paused') is not False
            or state.get('mode') != 'paper' or state.get('market_mode') != 'fomo_trending'
            or state.get('market_fresh') is not True
            or not 0 <= now - state.get('server_time', 0) <= 10):
        return []
    latest = {}
    for decision in sorted(records, key=lambda d:d['created_at'], reverse=True):
        if decision.get('run_id') != state['run_id'] or decision['created_at'] < accept_after:
            continue
        latest.setdefault(decision['bio_id'], decision)
    # A later HOLD supersedes an earlier BUY. Do not replay a backlog of orders.
    return sorted(latest.values(), key=lambda d:d['created_at'])


def private_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(encoded({'updated_at':time.time(), **report})+'\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(tmp,path)
