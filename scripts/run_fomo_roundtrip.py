"""Operator-run BUY/full-SELL acceptance check. Defaults to a non-submitting quote."""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import signal

from bio_arena.auto_execution import ExecutionStore
from bio_arena.execution_check import ExecutionCheck
from bio_arena.execution_service import load_config, private_report
from bio_arena.fomo_executor import FomoBrowserExecutor


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--bio',required=True)
    parser.add_argument('--token',required=True,help='Explicit Robinhood token contract; no automatic token selection')
    parser.add_argument('--check-id',default='execution-check-01',help='Reuse to inspect/resume; never repeats a verified order')
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--execute',action='store_true',help='Operator explicitly starts real BUY and full SELL; otherwise quote-only')
    parser.add_argument('--resume-exit',action='store_true',help='Resume only a verified entry exit with a fresh ten-minute window; requires --execute and never buys')
    parser.add_argument('--wrapper',type=Path,default=Path.home()/'.codex/skills/playwright/scripts/playwright_cli.sh')
    args=parser.parse_args(argv)
    if args.resume_exit and not args.execute:
        parser.error('--resume-exit requires --execute')
    os.umask(0o077)
    config,limits=load_config(args.config)
    if args.bio not in config['accounts']:
        parser.error('Bio is not bound to an account')
    directory=args.config.resolve().parent/'execution'
    directory.mkdir(exist_ok=True,parents=True,mode=0o700)
    mode='live' if args.execute else 'shadow'
    stopped=False

    def stop(*_):
        nonlocal stopped
        stopped=True

    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,stop)

    def enabled():
        return not stopped and not (directory/'STOP').exists()

    previous_stage=None

    def observe(report):
        nonlocal previous_stage
        # A changed configuration stops further attempts; it cannot silently
        # change the account or trade limits during an acceptance check.
        current,_=load_config(args.config)
        if current != config:stop()
        private_report(directory/f'{mode}-status.json',report)
        stage=report['check_stage']
        if stage != previous_stage:
            print(json.dumps({'mode':mode,'bio':args.bio,'stage':stage,
                'verified_fills':report['trial']['real_orders_verified']}),flush=True)
            previous_stage=stage

    with ExitStack() as stack:
        for account in sorted(config['accounts'].values(),key=lambda a:a['browser_directory']):
            handle=stack.enter_context((Path(account['browser_directory'])/'.bio-execution.lock').open('a'))
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        store=ExecutionStore(directory/f'{mode}.sqlite',mode,
            {b:a['account_ref'] for b,a in config['accounts'].items()},limits,
            identities={b:{k:v for k,v in a.items() if k!='enabled'} for b,a in config['accounts'].items()})
        stack.callback(store.close)
        check=ExecutionCheck(store,FomoBrowserExecutor(config['accounts'],args.wrapper),args.bio,args.token,
            args.check_id,seconds=args.seconds,enabled=enabled,observe=observe)
        if args.resume_exit:
            check.resume_exit_window()
        result=check.run()
        print(json.dumps({'passed':result['trial']['complete'],'stage':result['check_stage'],
            'trial':result['trial'],'last_status':(result['last'] or {}).get('status'),
            'reason':((result['last'] or {}).get('evidence') or {}).get('reason') or (result['last'] or {}).get('reason')}),flush=True)
        return 0 if result['trial']['complete'] or result['check_stage']=='quote_only' else 1


if __name__=='__main__':
    raise SystemExit(main())
