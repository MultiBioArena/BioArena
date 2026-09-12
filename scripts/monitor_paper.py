"""Local paper health and forward reports; no account controls or external messages."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.request

import psutil

from bio_arena.evaluation import report


def sample(root, url):
    now=time.time()
    with urllib.request.urlopen(url+'/api/state',timeout=10) as response:state=json.load(response)
    if state['mode']!='paper':raise ValueError('Monitor is restricted to paper experiments')
    run=root/'runs'/state['run_id']
    if run.resolve().parent!=(root/'runs').resolve():raise ValueError('Invalid local experiment ID')
    pointer=run/'recovery/latest.json';bundle=None
    if pointer.exists():
        name=json.loads(pointer.read_text())['bundle']
        if Path(name).name!=name:raise ValueError('Invalid recovery pointer')
        bundle=run/'recovery'/name
    runtime=json.loads((bundle/'runtime.json').read_text()) if bundle else None
    alerts=[]
    if state['status']=='error':alerts.append('arena_error')
    if not state['market_fresh']:alerts.append('stale_market')
    if state['paused']:alerts.append('operator_paused')
    if not runtime or now-runtime['at']>180:alerts.append('no_recent_complete_checkpoint')
    usage=psutil.disk_usage(root)
    if usage.free<2*1024**3:alerts.append('low_disk_space')
    processes=[]
    for process in psutil.process_iter(['pid','cmdline','memory_info']):
        try:
            cmd=process.info['cmdline'] or []
            if 'bio_arena.api:app' in cmd and Path(process.cwd()).resolve()==root:
                for p in [process]+process.children(recursive=True):
                    processes.append({'pid':p.pid,'rss_bytes':p.memory_info().rss,'cpu_seconds':sum(p.cpu_times()[:2])})
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    result={'observed_at':now,'run_id':state['run_id'],'sequence':state['sequence'],'status':state['status'],
            'alerts':alerts,'checkpoint_age_seconds':now-runtime['at'] if runtime else None,
            'recovery_bundles':len([p for p in pointer.parent.iterdir() if p.is_dir() and not p.name.startswith('.')]) if pointer.exists() else 0,
            'backend_rss_bytes':sum(p['rss_bytes'] for p in processes),'processes':processes,
            'event_database_bytes':sum(p.stat().st_size for p in run.glob('events.sqlite*')),
            'disk_free_bytes':usage.free,'bios':{b['id']:{'equity':b['account']['equity'],
            'valuation_stale':b['account']['valuation_stale'],'positions':b['account']['position_count'],
            'updates':b['training']['updates'],'active_version':b['training']['active_version'],
            'activity':(b.get('activity') or {}).get('state')} for b in state['bios']}}
    for bio,values in result['bios'].items():
        if values['valuation_stale']:alerts.append(f'{bio}:stale_valuation')
    evaluation=report(run)
    evaluation['cash_baseline']={'return_pct':0,'scope':'No trades, no yield; compare over the same recorded paper-account span'}
    return result,evaluation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8140')
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--interval',type=int,default=60)
    args=parser.parse_args()
    if args.interval<30:parser.error('Polling interval must be at least 30 seconds')
    root=Path(__file__).resolve().parents[1];directory=root/'output/monitor';directory.mkdir(parents=True,exist_ok=True)
    while True:
        try:
            status,evaluation=sample(root,args.url)
            temporary=directory/'.training.tmp';temporary.write_text(json.dumps(evaluation,allow_nan=False,indent=2))
            temporary.replace(directory/'training-latest.json')
        except Exception:
            status={'observed_at':time.time(),'alerts':['monitor_read_failed']}
        temporary=directory/'.latest.tmp';temporary.write_text(json.dumps(status,allow_nan=False,indent=2))
        temporary.replace(directory/'latest.json')
        day=datetime.now(timezone.utc).strftime('%Y%m%d')
        with (directory/f'{day}.jsonl').open('a') as log:log.write(json.dumps(status,allow_nan=False)+'\n')
        print(json.dumps({k:status[k] for k in ('observed_at','run_id','sequence','alerts') if k in status}),flush=True)
        if not args.watch:break
        time.sleep(args.interval)


if __name__=='__main__':main()
