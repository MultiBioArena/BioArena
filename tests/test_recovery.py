"""Recovery must preserve neural continuation and a consistent ledger boundary."""
import asyncio
from concurrent.futures import Future
import json
from pathlib import Path
import shutil

import numpy as np
import pytest
import yaml

from bio_arena.arena import Arena
from bio_arena.meme_arena import MemecoinArena
from bio_arena.learning import ReadoutLearner, FEATURE_NAMES
from bio_arena.registry import roster, seed_offset
from bio_arena.recovery import CORE, fork_restore, load_bundle, publish
from bio_arena.simulation import Brain

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.requires_data
@pytest.mark.parametrize('bio', ['worm','adult','larva'])
def test_neural_checkpoint_continues_exact_spikes_and_random_stream(tmp_path, bio):
    config = yaml.safe_load((ROOT/'configs/arena.yaml').read_text())
    before = Brain(ROOT,bio,config)
    features = dict(approach=.7,avoid=.1,volume=.3,volatility=.2)
    before.step(features)
    before.checkpoint(tmp_path)
    expected = before.step(features)
    after = Brain(ROOT,bio,config)
    after.restore(tmp_path)
    actual = after.step(features)
    for field in ('counts_sha256','score','sequence','neural_activity'):
        assert actual[field] == expected[field]
    assert np.array_equal(before.pending,after.pending)
    assert before.rng.bit_generator.state == after.rng.bit_generator.state
    saved=json.loads((tmp_path/f'{bio}.json').read_text());saved['seed']+=1
    (tmp_path/f'{bio}.json').write_text(json.dumps(saved))
    with pytest.raises(ValueError,match='seed'):after.restore(tmp_path)


def test_learner_roundtrip_preserves_candidate_pending_and_random():
    settings=yaml.safe_load((ROOT/'configs/fomo.yaml').read_text())['memecoin']['learning']
    learner=ReadoutLearner('worm',17,settings)
    learner.working[:]=.03;learner.active[:]=.02;learner.updates=42
    learner.candidate_sequence=3
    learner.candidate=dict(version=3,weights=np.ones(len(FEATURE_NAMES))*.1,frozen_at=500,
                           count=5,candidate_error=1.,active_error=2.,zero_error=3.)
    learner.pending=[{'id':'pending-fixture'}]
    payload=json.loads(json.dumps(learner.checkpoint()))
    restored=ReadoutLearner('worm',17,settings);restored.restore(payload)
    assert json.loads(json.dumps(restored.checkpoint())) == json.loads(json.dumps(learner.checkpoint()))
    assert restored.random.random() == learner.random.random()
    restored.working[0]=9
    assert learner.working[0] == .03


class CheckpointPool:
    """Only filesystem publication uses a stub; neural continuation is tested above."""
    def __init__(self,bio):self.bio=bio
    def submit(self,method,folder):
        path=Path(folder);(path/f'{self.bio}.json').write_text('{}')
        (path/f'{self.bio}.npz').write_bytes(b'boundary fixture')
        future=Future();future.set_result(None);return future


@pytest.mark.parametrize('multi',[False,True])
def test_resume_forks_ledger_boundary_without_mutating_source(tmp_path,multi):
    source_dir=tmp_path/'src/bio_arena';source_dir.mkdir(parents=True)
    for name in CORE:shutil.copyfile(ROOT/'src/bio_arena'/name,source_dir/name)
    config=yaml.safe_load((ROOT/('configs/fomo.yaml' if multi else 'configs/arena.yaml')).read_text())
    for key in roster(config):
        folder=tmp_path/'data/processed'/key;folder.mkdir(parents=True)
        for name in ('manifest.json','visual.json'):(folder/name).write_text('{}')
    kind=MemecoinArena if multi else Arena
    original=kind(tmp_path,config);resumed=None
    try:
        original.pools={k:CheckpointPool(k) for k in original.keys}
        original.status='running';original.started_at=100;original.sequence=1
        original.schedule.start(100)
        original.broker.accounts['worm'].cash=9876
        original.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',('committed',1,'worm',100,'{}'))
        original.db.commit()
        original.market_file.write('{"boundary":1}\n')
        original.histories['worm'].append({'time':100,'equity':9876})
        if multi:
            original.learners['worm'].updates=42
            original.learners['worm'].pending=[{'id':'outage-label'}]
        bundle=asyncio.run(publish(original))
        original.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',('crash-tail',2,'worm',101,'{}'))
        original.db.commit();original.market_file.write('{"tail":2}\n')
        path,payload=load_bundle(tmp_path,original.run_id)
        resumed=kind(tmp_path,config);fork_restore(resumed,path,payload)
        assert resumed.run_id != original.run_id
        assert resumed.sequence == 1 and resumed.started_at == 100
        assert resumed.broker.accounts['worm'].cash == 9876
        assert resumed.db.execute('SELECT id FROM decisions').fetchall() == [('committed',)]
        assert original.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 2
        assert (resumed.run_dir/'market.jsonl').read_text() == '{"boundary":1}\n'
        assert 'tail' in (original.run_dir/'market.jsonl').read_text()
        assert resumed.schedule.random['adult'].random()==original.schedule.random['adult'].random()
        if multi:
            assert resumed.learners['worm'].updates == 42
            assert resumed.learners['worm'].expired == 1 and not resumed.learners['worm'].pending
        (bundle/'worm.json').write_text('corrupt')
        with pytest.raises(ValueError,match='checksum'):load_bundle(tmp_path,original.run_id)
        assert (Path(resumed.worker_checkpoint)/'worm.json').read_text() == '{}'
    finally:
        for arena in (original,resumed):
            if arena:
                arena.db.close();arena.market_file.close()
                if multi:arena.board_file.close()


def test_legacy_recovery_rejected_and_identity_registry_stable(tmp_path):
    with pytest.raises(ValueError,match='legacy'):load_bundle(tmp_path,'old-run')
    assert seed_offset('worm','brain')==11
    assert seed_offset('adult','learner')==15401
    assert seed_offset('future_bio','brain')!=seed_offset('future_bio','learner')
    assert roster({'competitors':['worm','future_bio']})==['worm','future_bio']
    for values in ([],['worm','worm'],['../worm'],['bad/name'],['all'],['market']):
        with pytest.raises(ValueError):roster({'competitors':values})


@pytest.mark.requires_data
@pytest.mark.parametrize('legacy', [False, True])
def test_spawned_three_brains_publish_and_resume_with_portfolio(tmp_path, legacy):
    """Run real workers on an offline feed, then continue a new child experiment."""
    import time
    from copy import deepcopy
    source_dir=tmp_path/'src/bio_arena';source_dir.mkdir(parents=True)
    for name in CORE:shutil.copyfile(ROOT/'src/bio_arena'/name,source_dir/name)
    (tmp_path/'data').mkdir();(tmp_path/'data/processed').symlink_to(ROOT/'data/processed',target_is_directory=True)
    config=yaml.safe_load((ROOT/'configs/fomo.yaml').read_text())
    config.update(tick_seconds=1,round_seconds=0)
    config['decision_schedule']={'jitter_seconds':0,'minimum_gap_seconds':.1,'initial_offsets':{'worm':0,'adult':.2,'larva':.4}}
    config['memecoin'].update(warmup_quotes=2,warmup_seconds=0,bio_warmup_observations=0,trade_cooldown_seconds=0)
    asset={'asset_id':'bnb:0x'+'a'*40,'chain':'bnb','address':'0x'+'a'*40,'symbol':'OFFLINE',
           'url':'https://example.invalid/fixture','pair_address':'offline-pool'}

    def feed(arena):
        market=arena.market
        async def run():
            market.assets[asset['asset_id']]=asset;market.candidates[asset['asset_id']]=asset
            while True:
                now=time.time();market.board_at=now
                q={**asset,'id':f'fixture:{now}','price':10,'received_at':now,'source':'offline fixture',
                   'bid':10,'ask':10,'minute_volume':10000,'liquidity_usd':1e8,'volume_5m_usd':1e6,
                   'buys_5m':100,'sells_5m':100,'pair_created_at':1,'change_5m_pct':0}
                async with market.changed:
                    market.latest=q;market.quotes[asset['asset_id']]=q;market.histories[asset['asset_id']].append(q)
                    market.on_quote(q);market.changed.notify_all()
                await asyncio.sleep(.1)
        market.run=run

    async def wait_for(arena,predicate):
        async with asyncio.timeout(45):
            while not predicate():
                assert arena.status!='error',arena.error
                await asyncio.sleep(.1)

    async def exercise():
        first=MemecoinArena(tmp_path,deepcopy(config));feed(first)
        original_choose=first.choose
        def fixture_choice(bio,evaluations):
            chosen=original_choose(bio,evaluations)
            if not first.broker.accounts[bio].positions:
                chosen.update(action='BUY',allocation_fraction=.05,reason='Explicit offline lifecycle fixture')
            return chosen
        first.choose=fixture_choice
        await first.start()
        try:
            await wait_for(first,lambda:first.sequence>=4 and all(first.broker.accounts[k].positions for k in first.keys)
                           and (first.run_dir/'recovery/latest.json').exists())
            # Pause allows a currently computing decision to reach its published boundary.
            first.paused=True
            await wait_for(first,lambda:all(v=='waiting' for v in first.phases.values()) and first.status=='paused')
            if legacy:
                await first.checkpoint()
        finally:await first.stop()
        bundle,payload=load_bundle(tmp_path,first.run_id)
        assert payload['sequence']>=3
        child=MemecoinArena(tmp_path,deepcopy(config))
        if legacy:
            from bio_arena.migration import inspect_legacy, migrate_legacy
            shutil.rmtree(first.run_dir/'recovery')
            for key in first.keys:
                path=first.run_dir/f'models/{key}.json'
                model=json.loads(path.read_text());model.pop('candidate_sequence')
                path.write_text(json.dumps(model))
            source_hashes=inspect_legacy(tmp_path,first.run_id)['hashes']
            migrated=migrate_legacy(child,first.run_id)
            assert not migrated['exact_uninterrupted_replay'] and child.paused
            assert inspect_legacy(tmp_path,first.run_id)['hashes']==source_hashes
            assert not child.encoders['worm'] and child.market.board_at is None
            for key in child.keys:
                assert child.learners[key].active.tolist()==first.learners[key].active.tolist()
                assert child.learners[key].random.getstate()==first.learners[key].random.getstate()
            saved=first.run_dir/'stopped_state.json';valid=saved.read_text()
            invalid=json.loads(valid);invalid['sequence']+=1;saved.write_text(json.dumps(invalid))
            with pytest.raises((ValueError,FileNotFoundError)):inspect_legacy(tmp_path,first.run_id)
            saved.write_text(valid)
        else:
            fork_restore(child,bundle,payload)
        feed(child)
        for key in child.keys:
            assert child.broker.accounts[key].positions
            assert child.broker.accounts[key].cash==payload['accounts'][key]['cash']
        child.paused=False;sequence=child.sequence
        await child.start()
        try:
            await wait_for(child,lambda:child.sequence>sequence+2)
            assert child.db.execute('SELECT COUNT(*) FROM activity_events').fetchone()[0]>0
            for key in child.keys:
                assert child.telemetry[key]['sequence']>=payload['telemetry'][key]['sequence']
        finally:await child.stop()
    asyncio.run(exercise())
