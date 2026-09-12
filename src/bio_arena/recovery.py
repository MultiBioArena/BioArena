"""Versioned paper recovery bundles published only at complete decision boundaries."""
import asyncio
from collections import defaultdict, deque
from dataclasses import asdict
import hashlib
import json
import os
import platform
from importlib.metadata import version
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from .market import FeatureEncoder
from .portfolio import Portfolio, Position
from .trading import Account
from .simulation import save_checkpoint

VERSION = 1
CORE = ('arena.py', 'simulation.py', 'learning.py', 'market.py', 'meme_market.py',
        'meme_arena.py', 'portfolio.py', 'trading.py', 'policy.py', 'scheduling.py',
        'registry.py', 'recovery.py', 'activity.py')


def tuples(value):
    return tuple(tuples(x) for x in value) if isinstance(value, list) else value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_signature(root):
    return {name: digest(Path(root)/'src/bio_arena'/name) for name in CORE}


def environment_signature():
    return {'python':platform.python_version(),'machine':platform.machine(),
            'packages':{name:version(name) for name in ('numpy','numba','scipy')}}


def encoder_dump(encoder):
    return {name: list(getattr(encoder, name)) for name in ('prices', 'returns', 'volumes')}


def encoder_load(config, payload):
    encoder = FeatureEncoder(config)
    for name, values in payload.items():
        getattr(encoder, name).extend(values)
    return encoder


def runtime_dump(arena):
    multi = arena.config.get('market_source') == 'fomo_trending'
    tables = [r[0] for r in arena.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    # Names originate from the private SQLite schema, never from an HTTP request.
    if any(not name.replace('_', '').isalnum() for name in tables):
        raise ValueError('Unexpected event table')
    arena.market_file.flush()
    logs = {'market.jsonl': (arena.run_dir/'market.jsonl').stat().st_size}
    if multi:
        arena.board_file.flush()
        logs['candidates.jsonl'] = (arena.run_dir/'candidates.jsonl').stat().st_size
    payload = {'version': VERSION, 'source_run': arena.run_id, 'at': time.time(),
        'config': arena.config, 'keys': arena.keys, 'sequence': arena.sequence,
        'started_at': arena.started_at, 'ended_at': arena.ended_at, 'status': arena.status,
        'paused': arena.paused, 'activities': {k:v.checkpoint() for k,v in arena.activities.items()}, 'accounts': {k: asdict(a) for k,a in arena.broker.accounts.items()},
        'broker_seen': list(arena.broker.seen) if isinstance(arena.broker.seen,set) else arena.broker.seen,
        'histories': {k: list(v) for k,v in arena.histories.items()}, 'market_history': list(arena.market_history),
        'telemetry': arena.telemetry, 'recent': list(arena.recent), 'final_price': arena.final_price,
        'schedule': {'next_at': arena.schedule.next_at, 'last_completed': arena.schedule.last_completed,
                     'random': {k:r.getstate() for k,r in arena.schedule.random.items()}},
        'log_offsets': logs, 'rows': {name: arena.db.execute(f'SELECT COALESCE(MAX(rowid),0) FROM "{name}"').fetchone()[0] for name in tables},
        'code': code_signature(arena.root), 'environment': environment_signature(),
        'connectomes': {k: arena.metadata[k].get('processed_sha256', {}) for k in arena.keys}}
    if multi:
        payload.update(learners={k:v.checkpoint() for k,v in arena.learners.items()},
            encoders={k:{a:encoder_dump(e) for a,e in enc.items()} for k,enc in arena.encoders.items()},
            encoder_pairs=arena.encoder_pairs, reviewed=arena.reviewed, focus_assets=arena.focus_assets,
            selections=arena.selections, pending_accounts=arena.pending_accounts, frozen_accounts=arena.frozen_accounts,
            market={name:getattr(arena.market,name) for name in ('assets','candidates','quotes','latest','board_at')},
            quote_histories={k:list(v) for k,v in arena.market.histories.items()})
    else:
        payload.update(encoders={k:encoder_dump(v) for k,v in arena.encoders.items()},
            policies={k:{name:list(v) if isinstance(v,deque) else v for name,v in vars(p).items() if name not in ('config','settings')} for k,p in arena.policies.items()},
            market={'latest':arena.market.latest,'request_count':arena.market.request_count})
    # Freeze the parent before awaiting worker IO; fresh quotes can arrive while files are written.
    return json.loads(json.dumps(payload, allow_nan=False))


async def publish(arena):
    if not arena.pools or not all(phase == 'waiting' for phase in arena.phases.values()):
        return None
    payload = runtime_dump(arena)
    parent = arena.run_dir/'recovery';parent.mkdir(exist_ok=True)
    name = f'{arena.sequence:012d}-{uuid.uuid4().hex[:12]}'
    staging = parent/('.tmp-'+name);staging.mkdir()
    try:
        (staging/'runtime.json').write_text(json.dumps(payload,allow_nan=False))
        await asyncio.gather(*[asyncio.wrap_future(pool.submit(save_checkpoint,str(staging))) for pool in arena.pools.values()])
        hashes = {p.name:digest(p) for p in staging.iterdir() if p.is_file()}
        for path in staging.iterdir():
            with path.open('rb') as file: os.fsync(file.fileno())
        manifest = {'version':VERSION,'files':hashes,'sequence':arena.sequence}
        (staging/'manifest.json').write_text(json.dumps(manifest))
        with (staging/'manifest.json').open('rb') as file:os.fsync(file.fileno())
        directory=os.open(staging,os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        staging.rename(parent/name)
        pointer = parent/'.latest.tmp'
        pointer.write_text(json.dumps({'bundle':name}))
        with pointer.open('rb') as file:os.fsync(file.fileno())
        pointer.replace(parent/'latest.json')
        descriptor=os.open(parent,os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
        if os.getenv('BIO_ARENA_CONTINUE') == '1':
            active=arena.root/'runs/.active-run.tmp'
            active.write_text(json.dumps({'run_id':arena.run_id,'at':payload['at']}))
            with active.open('rb') as file:os.fsync(file.fileno())
            active.replace(arena.root/'runs/active-run.json')
            directory=os.open(arena.root/'runs',os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        # Keep two complete bundles; interrupted staging directories are never selected.
        complete=sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith('.'))
        for old in complete[:-2]:shutil.rmtree(old)
        return parent/name
    finally:
        if staging.exists():shutil.rmtree(staging)


def load_bundle(root, source):
    run = Path(root)/'runs'/str(source)
    if run.resolve().parent != (Path(root)/'runs').resolve():
        raise ValueError('Recovery source must be a run ID in this workspace')
    if (run/'result.json').exists():raise ValueError('Completed experiments cannot be resumed')
    stopped=run/'stopped_state.json'
    if stopped.exists() and json.loads(stopped.read_text()).get('status')=='error':
        raise ValueError('Failed experiments need review before recovery')
    pointer = run/'recovery/latest.json'
    if not pointer.exists():
        raise ValueError('No complete recovery bundle; legacy neural checkpoints alone cannot restore accounts and learning consistently')
    name = json.loads(pointer.read_text())['bundle']
    if Path(name).name != name or name.startswith('.'):
        raise ValueError('Invalid recovery pointer')
    bundle = pointer.parent/name
    manifest=json.loads((bundle/'manifest.json').read_text())
    if manifest['version'] != VERSION:raise ValueError('Unsupported recovery version')
    for name,expected in manifest['files'].items():
        if Path(name).name != name or digest(bundle/name)!=expected:raise ValueError('Recovery checksum mismatch')
    payload=json.loads((bundle/'runtime.json').read_text())
    if payload['source_run'] != str(source) or payload['code'] != code_signature(root) or payload.get('environment') != environment_signature():
        raise ValueError('Recovery source or trading code changed; an explicit migration is required')
    if payload['status'] in ('finished','error'):
        raise ValueError('Completed or failed experiments require review; they are not automatically resumed')
    expected={'runtime.json'} | {f'{bio}.{suffix}' for bio in payload['keys'] for suffix in ('json','npz')}
    if set(manifest['files']) != expected:raise ValueError('Incomplete recovery bundle')
    return bundle,payload


def fork_restore(arena, bundle, payload):
    """Resume into a new run ID, preserving the original log and any crash tail unchanged."""
    if payload['config'] != arena.config or payload['keys'] != arena.keys:
        raise ValueError('Recovery configuration or participant set changed')
    for key in arena.keys:
        if arena.metadata[key].get('processed_sha256',{}) != payload['connectomes'][key]:
            raise ValueError('Connectome data changed')
    source=arena.root/'runs'/payload['source_run']
    with sqlite3.connect(f'file:{source}/events.sqlite?mode=ro',uri=True) as original:
        original.backup(arena.db)
    with arena.db:
        for table,last in payload['rows'].items():
            if not table.replace('_','').isalnum():raise ValueError('Unexpected table')
            arena.db.execute(f'DELETE FROM "{table}" WHERE rowid>?',(last,))
    for name,offset in payload['log_offsets'].items():
        if name not in ('market.jsonl','candidates.jsonl') or (source/name).stat().st_size<offset:
            raise ValueError('Missing recovery event history')
        with (source/name).open('rb') as old,(arena.run_dir/name).open('wb') as new:
            remaining=offset
            while remaining:
                chunk=old.read(min(1024*1024,remaining));new.write(chunk);remaining-=len(chunk)
    arena.market_file.seek(0,2)
    arena.sequence=payload['sequence'];arena.started_at=payload['started_at'];arena.paused=payload['paused']
    arena.ended_at=None;arena.final_price=payload['final_price']
    for key,activity in arena.activities.items():activity.restore(payload['activities'][key])
    arena.histories={k:deque(v,maxlen=1200) for k,v in payload['histories'].items()}
    arena.market_history=deque(payload['market_history'],maxlen=240)
    arena.telemetry=payload['telemetry'];arena.recent=deque(payload['recent'],maxlen=80)
    arena.schedule.next_at=payload['schedule']['next_at'];arena.schedule.last_completed=payload['schedule']['last_completed']
    for key,state in payload['schedule']['random'].items():arena.schedule.random[key].setstate(tuples(state))
    multi=arena.config.get('market_source')=='fomo_trending'
    if multi:
        arena.broker.accounts={k:Portfolio(**{**a,'positions':{asset:Position(**p) for asset,p in a['positions'].items()}}) for k,a in payload['accounts'].items()}
        arena.broker.seen=payload['broker_seen']
        for key,learner in arena.learners.items():
            learner.restore(payload['learners'][key])
            # An outage has no observed minimum price; do not train on an invented continuous path.
            learner.expired+=len(learner.pending);learner.pending=[]
        arena.encoders={k:{a:encoder_load(arena.config,e) for a,e in enc.items()} for k,enc in payload['encoders'].items()}
        for name in ('encoder_pairs','focus_assets','selections','frozen_accounts'):setattr(arena,name,payload[name])
        arena.reviewed={k:defaultdict(float,v) for k,v in payload['reviewed'].items()}
        arena.pending_accounts={}
        arena.market.histories=defaultdict(lambda:deque(maxlen=360),{k:deque(v,maxlen=360) for k,v in payload['quote_histories'].items()})
        arena.board_file.seek(0,2)
    else:
        arena.broker.accounts={k:Account(**v) for k,v in payload['accounts'].items()};arena.broker.seen=set(payload['broker_seen'])
        arena.encoders={k:encoder_load(arena.config,e) for k,e in payload['encoders'].items()}
        for key,values in payload['policies'].items():
            for name,value in values.items():setattr(arena.policies[key],name,deque(value,maxlen=arena.config['opportunity_policy']['history_steps']) if name=='prices' else value)
            arena.policies[key].pending=None
    for name,value in payload['market'].items():setattr(arena.market,name,value)
    # The source may publish again and rotate its old bundles. Pin our verified copy.
    pinned = arena.run_dir/'restored_checkpoint'
    shutil.copytree(bundle,pinned)
    manifest_files=json.loads((pinned/'manifest.json').read_text())['files']
    if any(digest(pinned/name)!=expected for name,expected in manifest_files.items()):
        raise ValueError('Recovery bundle changed during the copy')
    arena.worker_checkpoint=str(pinned)
    manifest=json.loads((arena.run_dir/'manifest.json').read_text())
    manifest['recovery']={'source_run':payload['source_run'],'source_sequence':payload['sequence'],'checkpoint_at':payload['at'],
                          'bundle':bundle.name,'resumed_at':time.time(),'pending_labels':'discarded across the unobserved outage','history':'source log retained; child excludes entries after checkpoint'}
    (arena.run_dir/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
