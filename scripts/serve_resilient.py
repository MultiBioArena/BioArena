"""Paper supervision with validated recovery, hang detection and bounded retries."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request

from bio_arena.recovery import load_bundle
from bio_arena.watchdog import HealthWatch


def stop_group(child):
    try:os.killpg(child.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=10)
    # Worker processes must not remain after the server exits.
    try:os.killpg(child.pid,signal.SIGKILL)
    except ProcessLookupError:pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group();source.add_argument('--resume');source.add_argument('--migrate-legacy');source.add_argument('--new',action='store_true')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];pointer=root/'runs/active-run.json'
    env={**os.environ,'BIO_ARENA_CONTINUE':'1'}
    env.pop('BIO_ARENA_RESUME',None);env.pop('BIO_ARENA_MIGRATE_LEGACY',None)
    if args.migrate_legacy:env['BIO_ARENA_MIGRATE_LEGACY']=args.migrate_legacy
    elif args.resume or (not args.new and pointer.exists()):
        resume=args.resume or json.loads(pointer.read_text())['run_id'];load_bundle(root,resume);env['BIO_ARENA_RESUME']=resume
    elif not args.new:parser.error('No saved active run; choose an explicit initial source')
    directory=root/'runs/operations';directory.mkdir(exist_ok=True)
    logger=logging.getLogger('bio_supervisor');logger.setLevel(logging.INFO)
    handler=RotatingFileHandler(directory/'server.log',maxBytes=5*1024**2,backupCount=5)
    logger.addHandler(handler)
    child=None;stopping=False
    def stop(signum,frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    failures=0;url=f"http://127.0.0.1:{env.get('BIO_ARENA_PORT','8140')}/api/state"
    while not stopping:
        before=pointer.read_bytes() if pointer.exists() else None;started=time.monotonic()
        child=subprocess.Popen(['bash',str(root/'scripts/serve.sh')],cwd=root,env=env,start_new_session=True,
                               stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        def capture():
            for line in child.stdout:logger.info(line.rstrip())
        thread=threading.Thread(target=capture,daemon=True);thread.start()
        watch=HealthWatch(started,timeout=180,unreachable=60)
        reason=None
        while child.poll() is None and not stopping:
            try:
                with urllib.request.urlopen(url,timeout=3) as response:state=json.load(response)
            except (OSError,ValueError):state=None
            reason=watch.check(state,time.monotonic())
            if reason:break
            time.sleep(2)
        if stopping or reason:stop_group(child)
        else:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        thread.join(timeout=5)
        if stopping:return 0
        with (directory/'restarts.jsonl').open('a') as file:
            file.write(json.dumps({'at':time.time(),'reason':reason or 'process_exit','exit_code':child.returncode})+'\n')
        if reason=='engine_error':
            print('Engine error retained for operator review.',flush=True);return 2
        if not pointer.exists() or pointer.read_bytes()==before:
            print('No new recovery boundary: operator review required.',flush=True);return 2
        if time.monotonic()-started>=300:failures=0
        failures+=1
        if failures>2:print('Repeated server failure: recovery stopped.',flush=True);return 2
        resume=json.loads(pointer.read_text())['run_id'];load_bundle(root,resume)
        env.pop('BIO_ARENA_MIGRATE_LEGACY',None);env['BIO_ARENA_RESUME']=resume
        print('Recovering the last complete paper boundary.',flush=True);time.sleep(2)
    return 0


if __name__=='__main__':sys.exit(main())
