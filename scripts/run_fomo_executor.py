"""Run a separate FOMO executor. Defaults to quote rehearsal, never live orders."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import signal
import time

import httpx

from bio_arena.auto_execution import AutoExecutor, ExecutionStore
from bio_arena.execution_audit import PolicyExecutionAudit, require_execution_check
from bio_arena.execution_service import current_decisions, load_config, private_report
from bio_arena.execution_trial import ExecutionTrial, PortfolioTrial
from bio_arena.execution_exits import ExitSettings, LiveExitManager
from bio_arena.fomo_executor import FomoBrowserExecutor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    activation = parser.add_mutually_exclusive_group()
    activation.add_argument('--live', action='store_true', help='Operator-started continuous real execution; also requires enabled configuration')
    activation.add_argument('--start-live-trial', metavar='BIO', help='Explicitly arm one Bio for one real round trip in this process; saved enable switches are unchanged')
    parser.add_argument('--trial-id', default='first-live-cycle', help='Stable trial identity; reuse it to inspect/resume, never to repeat a completed cycle')
    parser.add_argument('--trial-seconds', type=int, default=3600, help='Maximum trial duration, including waiting for Bio signals')
    parser.add_argument('--require-execution-check', help='Require a completed operator BUY/SELL check for this Bio before starting the policy trial')
    parser.add_argument('--once', action='store_true', help='One shadow poll, including the latest fresh decisions')
    parser.add_argument('--managed-portfolio', action='store_true', help='Track actual holdings and retain exits after the entry window')
    parser.add_argument('--trial-entries', type=int, default=2, help='Maximum entries in a managed portfolio trial')
    parser.add_argument('--wait-for-browser', action='store_true', help='Wait for another operator-started executor to release the account browsers')
    parser.add_argument('--wrapper', type=Path, default=Path.home()/'.codex/skills/playwright/scripts/playwright_cli.sh')
    args = parser.parse_args(argv)
    is_live = bool(args.live or args.start_live_trial)
    if is_live and args.once:
        parser.error('--once is a non-submitting diagnostic only')
    if args.require_execution_check and not args.start_live_trial:
        parser.error('--require-execution-check requires --start-live-trial')
    if args.managed_portfolio and not args.start_live_trial:
        parser.error('--managed-portfolio requires --start-live-trial')
    os.umask(0o077)
    config, limits = load_config(args.config, live=args.live)
    if args.start_live_trial and args.start_live_trial not in config['accounts']:
        parser.error('Trial Bio is absent from the configured accounts')
    mode = 'live' if is_live else 'shadow'
    directory = args.config.resolve().parent / 'execution'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stop_file = directory / 'STOP'
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)

    def enabled():
        return not stopped and not stop_file.exists()

    with ExitStack() as stack:
        # Per-browser locks are shared by live and shadow modes and are independent
        # of journal names. Running a second config cannot double-drive a browser.
        for account in sorted(config['accounts'].values(), key=lambda a:a['browser_directory']):
            lock_path = Path(account['browser_directory']) / '.bio-execution.lock'
            handle = stack.enter_context(lock_path.open('a'))
            waiting_message = False
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not args.wait_for_browser:raise
                    if not enabled():return 1
                    if not waiting_message:
                        print('Waiting for the existing account executor to finish; no new orders submitted.',flush=True)
                        waiting_message = True
                    time.sleep(1)
        if not enabled():return 1
        if load_config(args.config,live=args.live)[0] != config:
            raise ValueError('Configuration changed while waiting for the browser')
        store = ExecutionStore(directory/f'{mode}.sqlite', mode,
            {bio:a['account_ref'] for bio,a in config['accounts'].items()}, limits,
            identities={bio:{k:v for k,v in a.items() if k!='enabled'} for bio,a in config['accounts'].items()})
        stack.callback(store.close)
        if args.require_execution_check:
            require_execution_check(store,args.require_execution_check,args.start_live_trial)
        exit_settings = ExitSettings(**config.get('exits',{})) if args.managed_portfolio else None
        if args.managed_portfolio:
            trial = PortfolioTrial(store,args.trial_id,args.start_live_trial,time.time(),args.trial_seconds,
                entry_target=args.trial_entries,exit_settings=asdict(exit_settings))
        else:
            trial = ExecutionTrial(store,args.trial_id,args.start_live_trial,time.time(),args.trial_seconds) if args.start_live_trial else None
        audit = PolicyExecutionAudit(store,trial.id if trial else f'feed-{time.time_ns()}')
        adapter = FomoBrowserExecutor(config['accounts'], args.wrapper)
        executor = AutoExecutor(store, adapter, clock=time.time, enabled=enabled,trial_id=trial.id if trial else None)
        client = stack.enter_context(httpx.Client(base_url=config['source_url'], timeout=5, trust_env=False))
        exit_client = stack.enter_context(httpx.Client(timeout=5,trust_env=False)) if args.managed_portfolio else None
        exits = LiveExitManager(store,exit_settings,exit_client) if args.managed_portfolio else None
        accept_after = 0 if args.once else time.time()
        seen = set()
        last = None
        def report(error=None, running=True):
            result = {**store.report(), 'last':last, 'error':error,
                'source':'Bio entry intents; persistent exits track real positions' if exits else 'Bio paper-policy intents; actual account checks and sizing are separate',
                'execution_kind':'bio_policy', 'policy_audit':audit.summary(),
                'live_enabled':is_live, 'process_running':running, 'independent_chain_finality_verified':False,
                'trial':trial.state(time.time()) if trial else None,
                'exit_management':exits.summary() if exits else None}
            private_report(directory/f'{mode}-status.json', result)
            return result

        active_phases = ('waiting_buy','waiting_sell','managing_positions','closing_positions')
        while enabled():
            if trial and trial.state(time.time())['phase'] not in active_phases:
                report()
                break
            # A changed configuration stops this process; restart deliberately to
            # apply new limits. It cannot silently enable additional accounts.
            fresh, _ = load_config(args.config, live=args.live)
            if fresh != config:
                raise ValueError('Configuration changed; restart the executor to apply it')
            state,records,selected = {},[],[]
            try:
                response = client.get('/api/state'); response.raise_for_status(); state = response.json()
                response = client.get('/api/decisions',params={'limit':30}); response.raise_for_status()
                records = response.json()
                selected = current_decisions(state, records, time.time(), accept_after=accept_after)
                if not selected:
                    accept_after = time.time()
                error = None
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                accept_after = time.time()
                error = 'Decision feed unavailable or invalid; new entries paused'
            try:
                if exits:
                    closing = time.time() >= trial.deadline
                    sell_decisions=exits.review(trial.bio,state,records,time.time(),close_all=closing)
                    for decision in sell_decisions:
                        last=audit.process(decision,executor,trial,time.time())
                        print(json.dumps({'bio':decision['bio_id'],'action':'SELL','status':last['status'],
                            'reason':last.get('reason') or (last.get('evidence') or {}).get('reason')}),flush=True)
                        report(error)
                        if trial.state(time.time())['phase'] not in active_phases:break
                    selected=[d for d in selected if d['action']!='SELL']
                    if sell_decisions or any(row['exit_requested'] for row in exits.summary()) or trial.state(time.time())['phase']=='closing_positions':selected=[]
                for decision in selected:
                    if decision['id'] in seen:
                        continue
                    seen.add(decision['id'])
                    account = config['accounts'].get(decision['bio_id'])
                    if not account or (args.live and not account['enabled']) or (trial and decision['bio_id']!=trial.bio):
                        continue
                    # Another Bio's browser call may have taken time. Recheck
                    # source status immediately before entering this account.
                    response = client.get('/api/state'); response.raise_for_status()
                    if not current_decisions(response.json(), [decision], time.time(), accept_after=accept_after):
                        continue
                    last = audit.process(decision,executor,trial,time.time())
                    print(json.dumps({'bio':decision['bio_id'],'action':decision['action'],
                        'status':last['status'],'reason':last.get('reason') or (last.get('evidence') or {}).get('reason')}),flush=True)
                    report()
                    if trial and trial.state(time.time())['phase'] not in active_phases:
                        break
                seen.intersection_update(d['id'] for d in records)
            except (httpx.HTTPError, KeyError, TypeError, ValueError):
                accept_after = time.time()
                error = 'Decision or exit evidence unavailable; no unverified order accepted'
            report(error)
            if args.once:
                break
            time.sleep(2)
        final = report(running=False)
        print(json.dumps({'mode':mode, 'status':'stopped', 'trial':final['trial'],
            'passed':bool(final['trial'] and final['trial']['complete']),
            'policy_audit':final['policy_audit'], 'journal':str(directory/f'{mode}.sqlite')}))
        return 0 if not trial or final['trial']['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
