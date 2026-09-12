"""Operator-run browser transport; delegates wallet handling to the FOMO UI."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
from .fomo_networks import NETWORKS


class FomoBrowserExecutor:
    def __init__(self, accounts, wrapper):
        self.accounts = accounts
        self.wrapper = Path(wrapper).resolve()
        self.source = Path(__file__).with_name('fomo_browser.js').read_text()

    def execute(self, intent, limits, *, live=False):
        account = self.accounts[intent['bio_id']]
        if account['account_ref'] != intent['account_ref']:
            raise ValueError('Browser account mismatch')
        options = {'intent': intent, 'limits': asdict(limits), 'live': live, 'networks': NETWORKS,
                   'account': {key: account[key] for key in ('profile','user_id','cash_wallet','token_wallet')}}
        code = 'async page => await ' + self.source + '(page, ' + json.dumps(options, allow_nan=False) + ')'
        result = subprocess.run(['bash', str(self.wrapper), 'run-code', code],
            cwd=account['browser_directory'], env={**os.environ, 'PLAYWRIGHT_CLI_SESSION': account['session']},
            capture_output=True, text=True, timeout=110)
        marker = '### Result\n'
        if result.returncode or marker not in result.stdout:
            raise RuntimeError('Browser result unavailable; order outcome is unknown')
        payload, _ = json.JSONDecoder().raw_decode(result.stdout.split(marker, 1)[1].lstrip())
        if not isinstance(payload, dict):
            raise RuntimeError('Malformed browser result')
        return payload
