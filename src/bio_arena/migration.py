"""Explicit conversion of a paused, gracefully stopped legacy paper experiment.

Financial, learned and neural state is retained. Missing market/encoder/scheduler
state is deliberately reinitialized and disclosed, never presented as exact replay.
"""
from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import time

from .portfolio import Portfolio, Position
from .registry import roster
from .recovery import digest
from .simulation import Brain


def inspect_legacy(root, source):
    run = Path(root) / 'runs' / source
    if run.resolve().parent != (Path(root) / 'runs').resolve():
        raise ValueError('Migration source must be a local run ID')
    if (run / 'result.json').exists() or (run / 'recovery/latest.json').exists():
        raise ValueError('Use compatible recovery for new runs; completed runs cannot migrate')
    state = json.loads((run / 'stopped_state.json').read_text())
    manifest = json.loads((run / 'manifest.json').read_text())
    config = manifest['config']
    keys = roster(config)
    if (state['run_id'] != source or manifest['run_id'] != source or state['mode'] != 'paper'
            or config['execution']['mode'] != 'paper' or config.get('market_source') != 'fomo_trending'
            or not state['paused'] or state['status'] != 'paused' or state.get('error')
            or state.get('ended_at') is not None or manifest['python'] != platform.python_version()):
        raise ValueError('Migration requires a paused, gracefully stopped compatible paper run')
    bios = {bio['id']: bio for bio in state['bios']}
    if list(bios) != keys or any(b['decision_clock']['phase'] not in ('waiting', 'out') for b in bios.values()):
        raise ValueError('A neural decision was still in progress')
    checkpoint = run / 'checkpoints' / str(state['sequence'])
    accounts = json.loads((checkpoint / 'portfolios.json').read_text())
    if list(accounts) != keys:
        raise ValueError('Incomplete final portfolio checkpoint')
    models = {}
    with sqlite3.connect(f'file:{run}/events.sqlite?mode=ro', uri=True) as db:
        if db.execute('SELECT COALESCE(MAX(seq),0) FROM decisions').fetchone()[0] != state['sequence']:
            raise ValueError('Final decision boundary does not match')
        for key in keys:
            a = accounts[key]
            account = Portfolio(**{**a, 'positions': {k: Position(**p) for k, p in a['positions'].items()}})
            if account.bio_id != key or account.initial_cash != config['initial_cash']:
                raise ValueError('Portfolio identity or initial capital changed')
            if account.public(state['server_time'], config['memecoin']['quote_max_age_seconds']) != bios[key]['account']:
                raise ValueError('Final portfolio differs from the stopped account')
            data = json.loads((Path(root) / f'data/processed/{key}/manifest.json').read_text())
            if data['processed_sha256'] != manifest['connectomes'][key]['processed_sha256']:
                raise ValueError('Connectome data changed')
            brain = Brain(root, key, config)
            brain.restore(checkpoint)
            row = db.execute('SELECT payload FROM observations WHERE bio_id=? ORDER BY rowid DESC LIMIT 1', (key,)).fetchone()
            if brain.sequence != (json.loads(row[0])['brain_sequence'] if row else 0):
                raise ValueError('Final neural checkpoint does not match observations')
            model = json.loads((run / f'models/{key}.json').read_text())
            if model['updates'] != db.execute('SELECT COUNT(*) FROM experiences WHERE bio_id=?', (key,)).fetchone()[0]:
                raise ValueError('Final learned state does not match experience history')
            for name in ('updates', 'samples', 'active_version', 'candidate_version'):
                if model[name] != bios[key]['training'][name]:
                    raise ValueError('Final model differs from stopped telemetry')
            versions = [json.loads(r[0])['version'] for r in db.execute('SELECT payload FROM model_events WHERE bio_id=?', (key,))]
            model['candidate_sequence'] = max([model['active_version'], (model.get('candidate') or {}).get('version', 0)] + versions)
            models[key] = model
    paths = [run / 'manifest.json', run / 'stopped_state.json', checkpoint / 'portfolios.json']
    paths += [checkpoint / f'{k}.{suffix}' for k in keys for suffix in ('json', 'npz')]
    paths += [run / f'models/{k}.json' for k in keys]
    return {'state': state, 'manifest': manifest, 'accounts': accounts, 'models': models,
            'hashes': {str(p.relative_to(run)): digest(p) for p in paths}}


def migrate_legacy(arena, source):
    evidence = inspect_legacy(arena.root, source)
    state, manifest = evidence['state'], evidence['manifest']
    if arena.config != manifest['config']:
        raise ValueError('Migration cannot change experiment configuration')
    run = arena.root / 'runs' / source
    # Capture the new schema before the read-only source backup replaces it.
    schema = arena.db.execute("SELECT sql FROM sqlite_master WHERE type IN ('table','index') AND sql IS NOT NULL").fetchall()
    with sqlite3.connect(f'file:{run}/events.sqlite?mode=ro', uri=True) as original:
        original.backup(arena.db)
    for (sql,) in schema:
        arena.db.execute(sql.replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ', 1)
                         .replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ', 1))
    arena.db.commit()
    for name, handle in [('market.jsonl', arena.market_file), ('candidates.jsonl', arena.board_file)]:
        shutil.copyfile(run / name, arena.run_dir / name)
        handle.seek(0, 2)
    arena.sequence, arena.started_at = state['sequence'], state['started_at']
    arena.paused = True
    arena.schedule.start(time.time())
    arena.recent = deque(state['recent_decisions'], maxlen=80)
    expired = {}
    for bio in state['bios']:
        key = bio['id']; a = evidence['accounts'][key]
        arena.broker.accounts[key] = Portfolio(**{**a, 'positions': {k: Position(**p) for k, p in a['positions'].items()}})
        learner = arena.learners[key]
        learner.restore(evidence['models'][key])
        expired[key] = len(learner.pending)
        learner.expired += expired[key]; learner.pending = []
        arena.telemetry[key] = bio['telemetry']
        arena.histories[key] = deque(bio['history'], maxlen=1200)
        arena.focus_assets[key] = bio['focus_asset_id']
        arena.selections[key] = bio['selection']
    for (payload,) in arena.db.execute('SELECT payload FROM decisions ORDER BY seq'):
        decision = json.loads(payload)
        arena.broker.seen[decision['intent']['id']] = decision['fill']
    # Asset identities must survive so held tokens are polled during fresh warmup.
    arena.market.assets = {a['asset_id']: {k: v for k, v in a.items() if k not in ('quote', 'fresh', 'in_trending', 'entry_problem')}
                           for a in state['assets']}
    pinned = arena.run_dir / 'migrated_checkpoint'
    shutil.copytree(run / 'checkpoints' / str(state['sequence']), pinned)
    arena.worker_checkpoint = str(pinned)
    if any(digest(run / name) != checksum for name, checksum in evidence['hashes'].items()):
        raise ValueError('Legacy source changed during migration')
    current = json.loads((arena.run_dir / 'manifest.json').read_text())
    current['migration'] = {'kind': 'legacy-paused-final-checkpoint-v1', 'source_run': source,
        'source_sequence': state['sequence'], 'at': time.time(), 'source_hashes': evidence['hashes'],
        'retained': ['full portfolios and marks', 'neural state and RNG', 'learned weights, candidates and RNG', 'event history'],
        'reset': ['market and feature warmup', 'scheduler RNG and deadlines', 'activity policy'],
        'expired_pending_labels': expired, 'exact_uninterrupted_replay': False,
        'accounts_at_migration': {k: asdict(a) for k, a in arena.broker.accounts.items()}}
    (arena.run_dir / 'manifest.json').write_text(json.dumps(current, allow_nan=False, indent=2))
    arena.save_models()
    return current['migration']
